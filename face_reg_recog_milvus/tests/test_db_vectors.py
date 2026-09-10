"""Async Milvus vector storage."""

from app.config import FACE_COLLECTION_NAME, FACE_METRIC_TYPE, FACE_VECTOR_DIM
from app.db import vectors


def unit_vector(seed: float) -> list[float]:
    """A simple L2-normalised vector, which is what COSINE search expects."""
    raw = [seed] + [0.0] * (FACE_VECTOR_DIM - 1)
    return [value / abs(seed) for value in raw]


async def test_insert_search_delete(clients, clean_stores):
    vector = unit_vector(1.0)
    await vectors.insert_vector(clients.milvus, FACE_COLLECTION_NAME, -301, vector)
    await clients.milvus.flush(FACE_COLLECTION_NAME)

    hits = await vectors.search(clients.milvus, FACE_COLLECTION_NAME, vector, FACE_METRIC_TYPE, limit=1)
    assert len(hits) == 1
    person_id, similarity = hits[0]
    assert person_id == -301
    # COSINE similarity with itself is 1.0. Higher is closer, unlike L2.
    assert similarity > 0.99

    await vectors.delete_vector(clients.milvus, FACE_COLLECTION_NAME, -301)
    await clients.milvus.flush(FACE_COLLECTION_NAME)
    assert await vectors.search(clients.milvus, FACE_COLLECTION_NAME, vector, FACE_METRIC_TYPE, limit=1) == []


async def test_search_on_empty_collection_returns_nothing(clients, clean_stores):
    assert await vectors.search(clients.milvus, FACE_COLLECTION_NAME, unit_vector(1.0), FACE_METRIC_TYPE) == []
