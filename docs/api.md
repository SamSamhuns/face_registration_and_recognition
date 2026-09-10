# HTTP API

Base path: `/api/v1`. Interactive documentation: `/docs`.

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

The image must contain exactly one face. The face must fill at least
`FACE_MIN_AREA_FRACTION` of the frame.

## Identify a face

`POST /api/v1/recognitions`, as `multipart/form-data`. Takes `image` or `image_url`,
the same way.

```bash
curl -X POST http://localhost:8080/api/v1/recognitions -F image=@probe.jpg
```

A match:

```json
{
  "matched": true,
  "match": { "person": { "id": 1, "name": "alice", "...": "..." }, "similarity": 0.97 },
  "detector": "scrfd_10g",
  "recognizer": "arcface_r50"
}
```

No match:

```json
{ "matched": false, "match": null, "detector": "scrfd_10g", "recognizer": "arcface_r50" }
```

No match is **200**, not an error. The request succeeded; the answer is negative.
`similarity` is cosine similarity, from -1 to 1. Higher is closer. A person is
returned only above `FACE_MATCH_THRESHOLD`.

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

There is no authentication. Do not expose this service to an untrusted network
without a gateway in front of it.

`image_url` refuses addresses that resolve to private, loopback or link-local
ranges. The download has a size limit and a time limit.
