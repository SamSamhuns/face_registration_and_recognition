"""
Person resource: /api/v1/persons

One resource, with HTTP verbs and status codes. The image source is a dependency, so
a file upload and a URL share the same endpoint.
"""

import logging
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.config import DOWNLOAD_IMAGE_PATH, MYSQL_CUR_TABLE
from app.db import persons as persons_db
from app.deps import Clients, get_clients
from app.errors import PersonNotFoundError, ValidationError
from app.schemas import PersonCreate, PersonList, PersonRead
from app.security import require_api_key
from app.services import enroll, images

router = APIRouter(prefix="/persons", tags=["persons"], dependencies=[Depends(require_api_key)])
logger = logging.getLogger("routes.persons")


async def image_source(
    image: Annotated[UploadFile | None, File(description="face image upload")] = None,
    image_url: Annotated[str | None, Form(description="alternative: fetch the image from a URL")] = None,
) -> Path:
    """
    Accept the face image from either a file upload or a URL, exactly one of the two.

    One dependency for both sources keeps /persons a single endpoint.
    """
    if (image is None) == (image_url is None):
        raise ValidationError("provide exactly one of 'image' (file upload) or 'image_url'")
    return await images.save_upload(image) if image is not None else await images.save_from_url(image_url)


async def person_form(
    person_id: Annotated[int, Form(alias="id", description="caller-assigned unique person id")],
    name: Annotated[str, Form(min_length=1, max_length=255)],
    birthdate: Annotated[date, Form(description="YYYY-MM-DD")],
    country: Annotated[str, Form(min_length=1, max_length=255)],
    city: Annotated[str, Form(max_length=255)] = "",
    title: Annotated[str, Form(max_length=255)] = "",
    org: Annotated[str, Form(max_length=255)] = "",
) -> PersonCreate:
    """
    Collect the person fields as flat multipart form fields.

    FastAPI only flattens a Pydantic model annotated with Form() when it is the ONLY
    body parameter. This endpoint also takes `image` and `image_url`, so a bare
    `Annotated[PersonCreate, Form()]` would instead demand a single form field
    literally named "person". Declaring the fields here keeps the wire format flat
    while the route still receives one validated PersonCreate.
    """
    return PersonCreate(
        id=person_id, name=name, birthdate=birthdate, country=country, city=city, title=title, org=org
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=PersonRead,
    summary="Register a person and their face",
)
async def create_person(
    person: Annotated[PersonCreate, Depends(person_form)],
    image_path: Annotated[Path, Depends(image_source)],
    clients: Annotated[Clients, Depends(get_clients)],
) -> PersonRead:
    """
    Register a person. 201 on success, 409 if the id is taken, 422 if the image has
    no usable face.

    `person` arrives as flat multipart form fields, so names and birthdates stay out
    of URLs and therefore out of access logs.
    """
    try:
        return await enroll.register_person(clients, MYSQL_CUR_TABLE, person, str(image_path))
    finally:
        images.discard(image_path)


@router.get("", response_model=PersonList, summary="List registered persons")
async def list_persons(
    clients: Annotated[Clients, Depends(get_clients)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PersonList:
    """Page through registered persons. `limit` bounds the reply size."""
    items, total = await persons_db.list_persons(clients.mysql, MYSQL_CUR_TABLE, limit, offset)
    return PersonList(items=items, total=total, limit=limit, offset=offset)


@router.get("/{person_id}", response_model=PersonRead, summary="Fetch one person")
async def get_person(
    person_id: int,
    clients: Annotated[Clients, Depends(get_clients)],
) -> PersonRead:
    """404 when there is no such person, rather than 200 with a failure payload."""
    return await enroll.get_person(clients, MYSQL_CUR_TABLE, person_id)


@router.delete(
    "/{person_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unregister a person",
)
async def delete_person(
    person_id: int,
    clients: Annotated[Clients, Depends(get_clients)],
) -> None:
    """204 with an empty body is the conventional answer to a successful DELETE."""
    await enroll.unregister_person(clients, MYSQL_CUR_TABLE, person_id)


@router.get(
    "/{person_id}/image",
    response_class=FileResponse,
    summary="Stored face image",
    responses={200: {"content": {"image/jpeg": {}}, "description": "The image used at registration"}},
)
async def get_person_image(
    person_id: int,
    clients: Annotated[Clients, Depends(get_clients)],
) -> FileResponse:
    """
    Return the image the person was registered with.

    `person_id` is declared as int, so FastAPI rejects anything else before this
    runs. That is what keeps the filename below free of path traversal: no caller
    can put a slash or a dot-dot into it.
    """
    # Look the person up first, so "no such person" and "image missing" differ.
    await enroll.get_person(clients, MYSQL_CUR_TABLE, person_id)

    path = Path(DOWNLOAD_IMAGE_PATH) / f"{person_id}.jpg"
    if not path.is_file():
        raise PersonNotFoundError(f"no stored image for person {person_id}")
    return FileResponse(path, media_type="image/jpeg")
