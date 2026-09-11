"""
Async Milvus access for face embeddings, via AsyncMilvusClient.

Replaces the ORM-style `Collection` API, which pymilvus deprecates and removes in
3.1, and which had no async support at all -- every search blocked the event loop.
"""

import logging

from pymilvus import AsyncMilvusClient, DataType

logger = logging.getLogger("db.vectors")

VECTOR_FIELD = "embedding"
ID_FIELD = "person_id"


async def ensure_collection(
    client: AsyncMilvusClient, name: str, dim: int, metric_type: str, index_type: str
) -> None:
    """Create and load the collection if it does not exist yet. Safe to re-run."""
    if not await client.has_collection(name):
        schema = client.create_schema(auto_id=False, description="face recognition system")
        schema.add_field(ID_FIELD, DataType.INT64, is_primary=True, description="person unique id")
        schema.add_field(VECTOR_FIELD, DataType.FLOAT_VECTOR, dim=dim, description="face embedding")

        index_params = client.prepare_index_params()
        index_params.add_index(field_name=VECTOR_FIELD, index_type=index_type, metric_type=metric_type)

        await client.create_collection(collection_name=name, schema=schema, index_params=index_params)
        logger.info("created milvus collection %s (%s/%s, dim=%s)", name, index_type, metric_type, dim)
    else:
        logger.info("milvus collection %s already present", name)

    await client.load_collection(name)


async def insert_vector(client: AsyncMilvusClient, collection: str, person_id: int, vector: list[float]) -> None:
    """Insert one embedding keyed by person_id."""
    await client.insert(collection_name=collection, data=[{ID_FIELD: person_id, VECTOR_FIELD: vector}])


async def search(
    client: AsyncMilvusClient, collection: str, vector: list[float], metric_type: str, limit: int = 1
) -> list[tuple[int, float]]:
    """
    Nearest neighbours for `vector`, as (person_id, similarity) ordered best-first.

    With COSINE the returned distance is the cosine similarity, so a higher value is
    a closer match. This is the opposite of an L2 distance.
    """
    results = await client.search(
        collection_name=collection,
        data=[vector],
        anns_field=VECTOR_FIELD,
        search_params={"metric_type": metric_type, "params": {}},
        limit=limit,
        output_fields=[ID_FIELD],
    )
    if not results or not results[0]:
        return []
    return [(hit["entity"][ID_FIELD], hit["distance"]) for hit in results[0]]


async def delete_vector(client: AsyncMilvusClient, collection: str, person_id: int) -> None:
    """Remove the embedding for person_id. A no-op if it is not there."""
    await client.delete(collection_name=collection, filter=f"{ID_FIELD} in [{int(person_id)}]")


async def ping(client: AsyncMilvusClient, collection: str) -> None:
    """Raise if Milvus is unreachable. Used by the readiness probe."""
    await client.has_collection(collection)
