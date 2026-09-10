"""The /persons resource, checked through HTTP."""

from tests.conftest import form_fields, person


async def test_create_returns_201_and_the_record(client, clean_stores, one_face):
    response = await client.post(
        "/api/v1/persons",
        data=form_fields(person(-401, "alice")),
        files={"image": ("face.jpg", one_face, "image/jpeg")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["id"] == -401
    assert body["name"] == "alice"


async def test_duplicate_id_returns_409(client, clean_stores, one_face):
    fields = form_fields(person(-402))
    files = {"image": ("face.jpg", one_face, "image/jpeg")}
    assert (await client.post("/api/v1/persons", data=fields, files=files)).status_code == 201

    response = await client.post("/api/v1/persons", data=fields, files=files)
    assert response.status_code == 409
    assert response.json()["error"] == "PersonAlreadyExistsError"


async def test_image_without_a_face_returns_422(client, clean_stores, no_face):
    response = await client.post(
        "/api/v1/persons",
        data=form_fields(person(-403)),
        files={"image": ("blank.jpg", no_face, "image/jpeg")},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "NoFaceDetectedError"


async def test_image_with_two_faces_returns_422(client, clean_stores, two_faces):
    response = await client.post(
        "/api/v1/persons",
        data=form_fields(person(-404)),
        files={"image": ("two.jpg", two_faces, "image/jpeg")},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "MultipleFacesError"


async def test_non_image_upload_returns_415(client, clean_stores):
    response = await client.post(
        "/api/v1/persons",
        data=form_fields(person(-405)),
        files={"image": ("notes.pdf", b"%PDF-1.4 not an image", "application/pdf")},
    )
    assert response.status_code == 415
    assert response.json()["error"] == "UnsupportedMediaTypeError"


async def test_missing_image_returns_400(client, clean_stores):
    response = await client.post("/api/v1/persons", data=form_fields(person(-406)))
    assert response.status_code == 400
    assert response.json()["error"] == "ValidationError"


async def test_get_unknown_person_returns_404(client, clean_stores):
    response = await client.get("/api/v1/persons/-999")
    assert response.status_code == 404
    assert response.json()["error"] == "PersonNotFoundError"


async def test_delete_then_get_returns_404(client, clean_stores, one_face):
    await client.post(
        "/api/v1/persons",
        data=form_fields(person(-407)),
        files={"image": ("face.jpg", one_face, "image/jpeg")},
    )
    assert (await client.delete("/api/v1/persons/-407")).status_code == 204
    assert (await client.get("/api/v1/persons/-407")).status_code == 404
    # A second delete has nothing to remove.
    assert (await client.delete("/api/v1/persons/-407")).status_code == 404


async def test_list_is_paginated(client, clean_stores, one_face):
    await client.post(
        "/api/v1/persons",
        data=form_fields(person(-408)),
        files={"image": ("face.jpg", one_face, "image/jpeg")},
    )
    response = await client.get("/api/v1/persons", params={"limit": 5, "offset": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 5
    assert [item["id"] for item in body["items"]] == [-408]
