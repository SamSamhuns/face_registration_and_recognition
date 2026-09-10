"""The /recognitions resource, checked through HTTP."""

from tests.conftest import form_fields, person


async def register(client, person_id: int, image: bytes):
    return await client.post(
        "/api/v1/persons",
        data=form_fields(person(person_id, "known")),
        files={"image": ("face.jpg", image, "image/jpeg")},
    )


async def test_known_face_is_matched(client, clean_stores, one_face):
    assert (await register(client, -501, one_face)).status_code == 201

    response = await client.post(
        "/api/v1/recognitions", files={"image": ("probe.jpg", one_face, "image/jpeg")}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is True
    assert body["match"]["person"]["id"] == -501
    assert body["match"]["similarity"] > 0.9


async def test_unknown_face_is_a_200_with_no_match(client, clean_stores, one_face, other_face):
    """Finding nobody is a successful request, not an error."""
    await register(client, -502, one_face)

    response = await client.post(
        "/api/v1/recognitions", files={"image": ("probe.jpg", other_face, "image/jpeg")}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is False
    assert body["match"] is None


async def test_empty_database_returns_no_match(client, clean_stores, one_face):
    response = await client.post(
        "/api/v1/recognitions", files={"image": ("probe.jpg", one_face, "image/jpeg")}
    )
    assert response.status_code == 200
    assert response.json()["matched"] is False


async def test_image_without_a_face_returns_422(client, clean_stores, no_face):
    response = await client.post(
        "/api/v1/recognitions", files={"image": ("blank.jpg", no_face, "image/jpeg")}
    )
    assert response.status_code == 422
    assert response.json()["error"] == "NoFaceDetectedError"


async def test_no_image_at_all_returns_400(client, clean_stores):
    response = await client.post("/api/v1/recognitions")
    assert response.status_code == 400
    assert response.json()["error"] == "ValidationError"
