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
    Run the face pipeline without blocking the event loop.

    TODO(human): implement this.

    Call _embed_sync(file_path) in a way that leaves the event loop free, and
    translate any faces.FaceError it raises using _translate() so the caller sees a
    domain error rather than a pipeline error.

    Shape to aim for:

        try:
            return await <something that runs _embed_sync off the loop>(file_path)
        except faces.FaceError as excep:
            raise _translate(excep) from excep

    The reasoning you need to reconstruct, because it is the whole point of this
    phase:

    Everything else in this codebase became async by swapping in an async driver --
    redis.asyncio, aiomysql, AsyncMilvusClient. That works because those operations
    are I/O bound: the process is idle waiting on a socket, and `await` hands that
    idle time to other tasks.

    _embed_sync is different. cv2.resize, the numpy decode maths and the warpAffine
    are CPU bound: the process is busy, not waiting. There is no async version of
    "do arithmetic", and rewriting it as `async def` would change nothing -- a
    coroutine that never awaits still owns the thread until it returns. Declaring
    something `async` does not make it yield; only an actual await point does.

    So the fix is not a different driver, it is a different *thread*. Look at
    asyncio.to_thread (3.9+), which runs a blocking callable in the default executor
    and gives you an awaitable. While it runs, the loop is free to serve other
    requests.

    This is also why app/services/triton.py still uses the SYNCHRONOUS gRPC client
    even though tritonclient.grpc.aio exists. The Triton call happens inside
    _embed_sync, which is already running in a worker thread -- and there is no
    event loop in that thread for an async client to attach to. Mixing the two would
    mean splitting the pipeline into async I/O steps with to_thread'd CPU steps
    between them, which buys nothing here: the CPU segments are milliseconds and the
    thread is already off the loop.

    Worth knowing about the ceiling: asyncio's default executor is a
    ThreadPoolExecutor, so concurrency is bounded by its worker count, and the
    CPU-bound parts still contend for the GIL (though numpy and OpenCV release it
    for the heavy operations). For this workload -- where a Triton round trip
    dominates -- that is entirely fine. If face processing ever became the
    bottleneck, the upgrade path is a ProcessPoolExecutor or a separate worker
    service, not more threads.
    """
    try:
        return await asyncio.to_thread(_embed_sync, file_path)
    except faces.FaceError as excep:
        raise _translate(excep) from excep


async def get_person(clients: Clients, table: str, person_id: int) -> PersonRead:
    """
    Read a person, cache-aside: try redis, fall back to mysql, warm the cache.

    Raises PersonNotFoundError so the route can answer 404 -- the old version
    returned {"status": "failed"} with HTTP 200.
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
    Register a person: embed their face, then persist across MySQL, Milvus and Redis.

    TODO(human): implement this.

    Building blocks, all already written and awaitable:

        await embed_face(file_path)                                  -> np.ndarray
        await persons.insert_person(clients.mysql, table, person)    -> None,
                                     raises PersonAlreadyExistsError
        await vectors.insert_vector(clients.milvus, FACE_COLLECTION_NAME,
                                    person.id, embedding.tolist())   -> None
        await persons.delete_person(clients.mysql, table, person.id) -> bool
        await cache.set_person(clients.redis, table, record, REDIS_CACHE_TTL_SECONDS)

    Return a PersonRead. You can build one with
    PersonRead(**person.model_dump()) since PersonCreate carries every field.

    The design decisions, which is why this one is yours:

    1. ORDER. These are three separate systems with no shared transaction, so
       "atomic" is not available -- despite what the old code's comment claimed.
       What you get to choose is which failure mode you prefer. Embedding first is
       clearly right (it is the most likely thing to fail, and it touches no
       state). After that: if MySQL succeeds and Milvus fails, you have a person
       who can never be recognised. If Milvus succeeds and MySQL fails, you have a
       vector pointing at a person who does not exist -- which is the failure that
       produced the "{person_id} does not exist" bug we hit in phase 1. Consider
       which of those is easier to detect and to clean up.

    2. COMPENSATION. Whichever you write second, decide what happens when it
       fails. Rolling back the first write (a compensating delete) keeps the stores
       consistent; leaving it and logging keeps the code shorter but accumulates
       orphans. If you compensate, remember the compensating call can itself fail --
       and that swallowing the original exception to report the cleanup failure
       instead would hide the actual cause.

    3. CACHE. The cache write is not part of correctness: a missing cache entry is
       a miss, which is harmless. So it should never be able to fail the request.
       Decide whether to write it at all here, or just let the first read populate
       it.

    4. DUPLICATES. Do not pre-check whether the id exists. insert_person surfaces
       the PRIMARY KEY violation as PersonAlreadyExistsError; just let it propagate
       and the route will answer 409. A check-then-insert is racy.
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
    # COSINE: higher is closer. This comparison is inverted from the old L2 code.
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
