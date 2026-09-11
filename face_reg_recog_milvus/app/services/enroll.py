"""
Registration and recognition orchestration.

This is the layer that knows about MySQL *and* Milvus *and* Redis *and* the face
pipeline. Routes stay thin, the db/ modules stay dumb, and the coordination
problems (write ordering, cache invalidation, cleanup after partial failure) all
live in one readable place.
"""

import asyncio
import logging

import numpy as np

from app.config import (
    FACE_COLLECTION_NAME,
    FACE_DET_THRESHOLD,
    FACE_DETECTOR,
    FACE_MATCH_THRESHOLD,
    FACE_METRIC_TYPE,
    FACE_MIN_AREA_FRACTION,
    FACE_RECOGNIZER,
    REDIS_CACHE_TTL_SECONDS,
)
from app.db import cache, persons, vectors
from app.deps import Clients
from app.errors import (
    InvalidImageError,
    MultipleFacesError,
    NoFaceDetectedError,
    PersonNotFoundError,
)
from app.schemas import Match, PersonCreate, PersonRead, RecognitionResult
from app.services import faces

logger = logging.getLogger("services.enroll")


def _translate(excep: faces.FaceError) -> Exception:
    """
    Map a face-pipeline error onto a domain error.

    faces.py has no idea HTTP exists -- this is the seam that keeps it that way.
    """
    if isinstance(excep, faces.NoFaceDetectedError):
        return NoFaceDetectedError(str(excep))
    if isinstance(excep, faces.TooManyFacesError):
        return MultipleFacesError(str(excep))
    return InvalidImageError(str(excep))


def _embed_sync(file_path: str) -> np.ndarray:
    """
    The whole CPU-bound pipeline: decode, detect, align, embed.

    Deliberately synchronous. See embed_face() for why.
    """
    img = faces.read_image(file_path)
    embedding, _face = faces.embed_primary_face(
        img,
        detector=FACE_DETECTOR,
        recognizer=FACE_RECOGNIZER,
        det_thresh=FACE_DET_THRESHOLD,
        min_area_fraction=FACE_MIN_AREA_FRACTION,
        max_faces=1,
    )
    return embedding


async def embed_face(file_path: str) -> np.ndarray:
    """
    Run the face pipeline without holding the event loop.

    The rest of this codebase became async by changing driver: redis.asyncio,
    aiomysql and AsyncMilvusClient all release the loop while they wait on a socket.

    _embed_sync is different. It is arithmetic in NumPy and OpenCV, so the process is
    busy, not waiting. An `async def` around it would change nothing, because a
    coroutine only yields at an await. The answer is a different thread, not a
    different driver, so asyncio.to_thread runs it in the default executor.

    This is also why app/services/triton.py keeps the synchronous gRPC client. It
    runs inside this worker thread, and a worker thread has no event loop.

    The ceiling: the default executor is a thread pool, so concurrency is bounded by
    its worker count. That is acceptable while a Triton round trip dominates the
    time. If face processing becomes the limit, move to a process pool or a separate
    worker service.
    """
    try:
        return await asyncio.to_thread(_embed_sync, file_path)
    except faces.FaceError as excep:
        raise _translate(excep) from excep


async def get_person(clients: Clients, table: str, person_id: int) -> PersonRead:
    """
    Read a person, cache-aside: try redis, fall back to mysql, warm the cache.

    Raises PersonNotFoundError, so the route can answer 404.
    """
    cached = await cache.get_person(clients.redis, table, person_id)
    if cached is not None:
        logger.info("person %s served from redis cache", person_id)
        return cached

    person = await persons.get_person(clients.mysql, table, person_id)
    if person is None:
        raise PersonNotFoundError(f"no registered person with id {person_id}")

    await cache.set_person(clients.redis, table, person, REDIS_CACHE_TTL_SECONDS)
    return person


async def register_person(clients: Clients, table: str, person: PersonCreate, file_path: str) -> PersonRead:
    """
    Register a person: embed the face, then write to MySQL, Milvus and Redis.

    The three stores share no transaction, so the write cannot be atomic. The order
    limits the damage instead. MySQL is written first, because a failure there leaves
    nothing behind. If Milvus then fails, the MySQL row is deleted, so no vector can
    point at a person who does not exist.

    A failure to clean up is logged and the original error is raised, because the
    original error is the useful one.

    The cache write is not part of correctness. A missing entry is only a cache miss.

    Duplicate ids are not checked first. insert_person reports the PRIMARY KEY
    violation, which is race free, and the route turns it into a 409.
    """
    face_embedding = await embed_face(file_path)
    await persons.insert_person(clients.mysql, table, person)
    try:
        await vectors.insert_vector(clients.milvus, FACE_COLLECTION_NAME, person.id, face_embedding.tolist())
    except Exception as excep:
        logger.error("failed to insert vector for person %s: %s. Attempting cleanup.", person.id, excep)
        try:
            await persons.delete_person(clients.mysql, table, person.id)
        except Exception as cleanup_excep:
            logger.error("failed to clean up person %s after vector insert failure: %s", person.id, cleanup_excep)
        raise
    await cache.set_person(clients.redis, table, PersonRead(**person.model_dump()), REDIS_CACHE_TTL_SECONDS)
    return PersonRead(**person.model_dump())


async def recognize(clients: Clients, table: str, file_path: str) -> RecognitionResult:
    """
    Identify the face in an image against the registered population.

    Worked example for the pattern register_person() needs: embed, hit a store,
    translate the outcome into a schema object.
    """
    embedding = await embed_face(file_path)

    hits = await vectors.search(
        clients.milvus, FACE_COLLECTION_NAME, embedding.tolist(), FACE_METRIC_TYPE, limit=1
    )
    if not hits:
        return RecognitionResult(matched=False, detector=FACE_DETECTOR, recognizer=FACE_RECOGNIZER)

    person_id, similarity = hits[0]
    # COSINE: a higher score is a closer match.
    if similarity < FACE_MATCH_THRESHOLD:
        logger.info("closest match %s scored %.3f, below threshold %.3f", person_id, similarity, FACE_MATCH_THRESHOLD)
        return RecognitionResult(matched=False, detector=FACE_DETECTOR, recognizer=FACE_RECOGNIZER)

    try:
        person = await get_person(clients, table, person_id)
    except PersonNotFoundError:
        # A vector outlived its person row. Report no match rather than 500, and
        # leave a loud log line -- this means the two stores have drifted.
        logger.error("milvus holds a vector for person %s with no mysql row", person_id)
        return RecognitionResult(matched=False, detector=FACE_DETECTOR, recognizer=FACE_RECOGNIZER)

    return RecognitionResult(
        matched=True,
        match=Match(person=person, similarity=similarity),
        detector=FACE_DETECTOR,
        recognizer=FACE_RECOGNIZER,
    )


async def unregister_person(clients: Clients, table: str, person_id: int) -> None:
    """
    Remove a person from all three stores.

    Deletes are ordered most-authoritative first and are individually idempotent,
    so a partial failure can be fixed by simply retrying the same call.
    """
    deleted = await persons.delete_person(clients.mysql, table, person_id)
    if not deleted:
        raise PersonNotFoundError(f"no registered person with id {person_id}")

    await vectors.delete_vector(clients.milvus, FACE_COLLECTION_NAME, person_id)
    await cache.invalidate(clients.redis, table, person_id)
    logger.info("person %s unregistered", person_id)
