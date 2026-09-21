# HTTP API

Base path: `/api/v1`. Interactive documentation: `/docs`.

## Authentication

Every `/api/v1` route needs an access token issued by Authentik, in the
`Authorization` header. Without one the answer is **401**.

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/persons
```

The API verifies the signature against Authentik's published public key, and checks
the issuer, the audience and the expiry. It holds no passwords and no shared key.

Authorization is by Authentik group, carried in the token's `groups` claim:

| Group | May |
| --- | --- |
| `face-operator` | `POST /recognitions`, and read `/persons` |
| `face-admin` | that, and `POST` or `DELETE` a person |

A verified token from an account in neither group is refused with **403**. The two
are different answers on purpose: 401 means the caller is nobody, 403 means the
caller is known and not permitted.

Open without a token: `/health` and `/health/ready`, because a load balancer probe
cannot carry one, and `/api/v1/auth/config`, because the browser reads it before it
has one.

[auth.md](auth.md) has the Authentik setup and the failures worth recognising.

Every error uses the same body.

```json
{ "error": "PersonNotFoundError", "detail": "no registered person with id 42" }
```

`error` is the error class name. Use it in code. `detail` is for a person to read.

## Register a person

`POST /api/v1/persons`, as `multipart/form-data`.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | integer | yes | Chosen by the caller. Must be unique. |
| `name` | string | yes | 1 to 255 characters |
| `birthdate` | date | yes | `YYYY-MM-DD` |
| `country` | string | yes | 1 to 255 characters |
| `city` | string | no | |
| `title` | string | no | |
| `org` | string | no | |
| `image` | file | one of two | The face image |
| `image_url` | string | one of two | Address of the face image |

Give either `image` or `image_url`, and not both.

```bash
curl -X POST http://localhost:8080/api/v1/persons \
  -F id=1 -F name=alice -F birthdate=1990-01-01 -F country=NP \
  -F image=@face.jpg
```

| Status | Meaning |
| --- | --- |
| 201 | Registered. The body is the person record. |
| 400 | Neither `image` nor `image_url`, or both. Or the URL could not be fetched. |
| 409 | That `id` is already registered. |
| 413 | The image is larger than `MAX_UPLOAD_BYTES`. |
| 415 | The upload is not an accepted image type. |
| 422 | No face in the image, more than one face, or a bad form field. |
| 503 | A dependency is unavailable. |

Registration needs exactly **one** face, and answers 422 for a group photograph. A
person record must point at an unambiguous face. Recognition has no such limit.
The face must fill at least `FACE_MIN_AREA_FRACTION` of the frame.

## Identify a face

`POST /api/v1/recognitions`, as `multipart/form-data`. Takes `image` or `image_url`,
the same way.

```bash
curl -X POST http://localhost:8080/api/v1/recognitions -F image=@probe.jpg
```

Every face in the image is reported, most confident first.

```json
{
  "faces": [
    {
      "box": { "x1": 551, "y1": 59, "x2": 710, "y2": 293 },
      "score": 0.90,
      "matched": true,
      "match": { "person": { "id": 1, "name": "alice", "...": "..." }, "similarity": 0.97 }
    },
    {
      "box": { "x1": 310, "y1": 94, "x2": 470, "y2": 333 },
      "score": 0.84,
      "matched": false,
      "match": null
    }
  ],
  "detector": "scrfd_10g",
  "recognizer": "arcface_r50"
}
```

`box` is in the pixels of the image you sent. `score` is detector confidence.

A face nobody matches is **200** with `matched: false`. The request succeeded; the
answer is negative. `similarity` is cosine similarity from -1 to 1, higher is closer,
and a person is returned only above `FACE_MATCH_THRESHOLD`.

`FACE_MAX_FACES`, 10 by default, caps how many faces one image may contain. Each face
costs an alignment, an embedding and a vector search, so a crowd photograph is
otherwise a cheap way to load the service.

| Status | Meaning |
| --- | --- |
| 200 | The search ran. Read `matched`. |
| 400, 413, 415, 422, 503 | The same as for registration. |

## List persons

`GET /api/v1/persons?limit=50&offset=0`

`limit` is 1 to 200, and 50 by default. `offset` is 0 or more.

```json
{ "items": [ { "id": 1, "name": "alice", "...": "..." } ], "total": 1, "limit": 50, "offset": 0 }
```

## Read one person

`GET /api/v1/persons/{id}` gives 200 with the record, or 404.

The service reads Redis first, then MySQL. A MySQL read fills the cache.

## Read the stored face image

`GET /api/v1/persons/{id}/image` returns the photograph the person was registered
with, as `image/jpeg`. 404 when there is no such person, or no stored image for them.

The image is saved on a best-effort basis at registration. A failed save leaves the
person registered and recognisable, and this route answers 404 for them.

## Remove a person

`DELETE /api/v1/persons/{id}` gives 204 with an empty body, or 404.

It removes the SQL row, the vector, and the cache entry.

## Health

`GET /health` reports that the process runs. It contacts no dependency. Use it for a
container restart rule.

`GET /health/ready` contacts MySQL, Redis and Milvus. It gives 200 when all answer,
and 503 when any fails. Use it for a load balancer.

```json
{
  "status": "ready",
  "dependencies": { "detector": "scrfd_10g", "recognizer": "arcface_r50",
                    "mysql": "ok", "redis": "ok", "milvus": "ok" }
}
```

## Notes

Every route under `/api/v1` needs a token, and a group. See [auth.md](auth.md).

`image_url` refuses addresses that resolve to private, loopback or link-local
ranges. The download has a size limit and a time limit.
