"""Liveness and readiness endpoints."""


async def test_liveness_touches_no_dependency(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


async def test_readiness_reports_each_dependency(client):
    response = await client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    for name in ("mysql", "redis", "milvus"):
        assert body["dependencies"][name] == "ok"
