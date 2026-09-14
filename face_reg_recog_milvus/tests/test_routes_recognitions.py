"""The /recognitions resource, checked through HTTP."""

from tests.conftest import form_fields, person


async def register(client, person_id: int, image: bytes):
    return await client.post(
        "/api/v1/persons",
        data=form_fields(person(person_id, "known")),
        files={"image": ("face.jpg", image, "image/jpeg")},
    )


async def recognize(client, image: bytes):
    return await client.post("/api/v1/recognitions", files={"image": ("probe.jpg", image, "image/jpeg")})


async def test_known_face_is_matched(client, clean_stores, one_face):
    assert (await register(client, -501, one_face)).status_code == 201

    response = await recognize(client, one_face)
    assert response.status_code == 200
    body = response.json()
    assert len(body["faces"]) == 1

    face = body["faces"][0]
    assert face["matched"] is True
    assert face["match"]["person"]["id"] == -501
    assert face["match"]["similarity"] > 0.9
    # The box must be inside the image and not empty.
    assert face["box"]["x2"] > face["box"]["x1"]
    assert face["box"]["y2"] > face["box"]["y1"]


async def test_unknown_face_is_a_200_with_no_match(client, clean_stores, one_face, other_face):
    """Finding nobody is a successful request, not an error."""
    await register(client, -502, one_face)

    body = (await recognize(client, other_face)).json()
    assert len(body["faces"]) == 1
    assert body["faces"][0]["matched"] is False
    assert body["faces"][0]["match"] is None


async def test_empty_database_returns_a_face_with_no_match(client, clean_stores, one_face):
    body = (await recognize(client, one_face)).json()
    assert len(body["faces"]) == 1
    assert body["faces"][0]["matched"] is False


async def test_two_faces_are_both_reported(client, clean_stores, two_faces):
    """A group photograph is no longer refused. Every face comes back."""
    response = await recognize(client, two_faces)
    assert response.status_code == 200
    body = response.json()
    assert len(body["faces"]) == 2
    # detect() returns the most confident first
    assert body["faces"][0]["score"] >= body["faces"][1]["score"]
    # Two different faces, so two different boxes.
    assert body["faces"][0]["box"] != body["faces"][1]["box"]


async def test_image_without_a_face_returns_422(client, clean_stores, no_face):
    response = await recognize(client, no_face)
    assert response.status_code == 422
    assert response.json()["error"] == "NoFaceDetectedError"


async def test_no_image_at_all_returns_400(client, clean_stores):
    response = await client.post("/api/v1/recognitions")
    assert response.status_code == 400
    assert response.json()["error"] == "ValidationError"
