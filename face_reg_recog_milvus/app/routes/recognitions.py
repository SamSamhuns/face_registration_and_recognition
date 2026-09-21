"""
Recognition resource: /api/v1/recognitions

POST creates a recognition *attempt* and returns its result. A lookup that finds
nobody is still a successful request, so it is 200 with matched=false -- not an
error. Only a request we could not process becomes non-2xx.
"""

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import MYSQL_CUR_TABLE
from app.deps import Clients, get_clients
from app.routes.persons import image_source
from app.schemas import RecognitionResult
from app.security import require_operator
from app.services import enroll, images

router = APIRouter(prefix="/recognitions", tags=["recognition"], dependencies=[Depends(require_operator)])
logger = logging.getLogger("routes.recognitions")


@router.post("", response_model=RecognitionResult, summary="Identify a face")
async def recognize(
    image_path: Annotated[Path, Depends(image_source)],
    clients: Annotated[Clients, Depends(get_clients)],
) -> RecognitionResult:
    """Identify the face in the supplied image against the registered population."""
    try:
        return await enroll.recognize(clients, MYSQL_CUR_TABLE, str(image_path))
    finally:
        images.discard(image_path)
