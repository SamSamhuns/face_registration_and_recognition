"""
Liveness and readiness.

These answer different questions and must not be conflated. /health says the
process is running -- that is what a container restart policy should watch.
/health/ready says the process can actually serve traffic, which means its
dependencies answered. A load balancer wants readiness; restarting a pod because
Milvus blipped would be the wrong response.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.config import FACE_COLLECTION_NAME, FACE_DETECTOR, FACE_RECOGNIZER
from app.db import cache, persons, vectors
from app.deps import Clients, get_clients
from app.schemas import HealthStatus

router = APIRouter(tags=["health"])
logger = logging.getLogger("routes.health")


@router.get("/health", response_model=HealthStatus, summary="Liveness probe")
async def health() -> HealthStatus:
    """Says the process is up. Deliberately touches no dependency."""
    return HealthStatus(status="healthy")


@router.get("/health/ready", response_model=HealthStatus, summary="Readiness probe")
async def ready(
    response: Response,
    clients: Annotated[Clients, Depends(get_clients)],
) -> HealthStatus:
    """Check every dependency, reporting 503 if any of them is unreachable."""
    checks: dict[str, str] = {"detector": FACE_DETECTOR, "recognizer": FACE_RECOGNIZER}
    healthy = True

    for name, probe in (
        ("mysql", persons.ping(clients.mysql)),
        ("redis", cache.ping(clients.redis)),
        ("milvus", vectors.ping(clients.milvus, FACE_COLLECTION_NAME)),
    ):
        try:
            await probe
            checks[name] = "ok"
        except Exception as excep:  # noqa: BLE001 - a probe reports, it does not raise
            logger.warning("readiness probe failed for %s: %s", name, excep)
            checks[name] = f"error: {type(excep).__name__}"
            healthy = False

    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthStatus(status="ready" if healthy else "degraded", dependencies=checks)
