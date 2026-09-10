# Architecture

## Services

Docker Compose starts these containers.

```
                 browser / client
                        |
                        v
      +-----------------------------------+
      |  api        (FastAPI + uvicorn)    |
      |  port 8080                         |
      +-----------------------------------+
         |          |          |        |
   gRPC  |     SQL  |   vector |  cache |
         v          v          v        v
    +--------+  +-------+  +--------+  +-------+
    | triton |  | mysql |  | milvus |  | redis |
    +--------+  +-------+  +--------+  +-------+
                                |
                          +-----+-----+
                          | etcd|minio|   (Milvus needs both)
                          +-----------+
```

The `api` and `triton` containers are separate on purpose. They ran as two processes
in one container before. When the API process failed, the container stayed up,
because the shell was still waiting for Triton. Two containers give each process its
own healthcheck and its own restart.

Triton uses the stock upstream image. The model repository is a bind mount, so new
model weights need no image build.

## Code layers

```
app/
  server.py        application object, lifespan, error handler
  config.py        environment variables, read once at import
  deps.py          client lifecycle, and the Depends providers
  errors.py        domain errors, and the error to HTTP status map
  schemas.py       request and response models
  routes/          HTTP only: parse the request, serialise the response
    persons.py     /api/v1/persons
    recognitions.py  /api/v1/recognitions
    health.py      /health and /health/ready
  services/        the work
    enroll.py      coordinates the stores
    faces.py       detect, align, embed
    images.py      accept an upload or a URL, safely
    triton.py      the shared Triton client
  db/              one module for each store
    persons.py     MySQL
    vectors.py     Milvus
    cache.py       Redis
```

Each layer may call the layer below it, never the layer above.

`services/faces.py` does not import `errors.py`. It is a face-processing module with
no knowledge of HTTP, so a batch script can use it. `services/enroll.py` translates
its errors into domain errors.

## One registration request

```
POST /api/v1/persons
  routes/persons.py
    person_form()      -> collect the form fields into a PersonCreate
    image_source()     -> images.save_upload() or images.save_from_url()
                          checks the type, streams to disk, applies a size limit
    enroll.register_person()
      embed_face()             -> asyncio.to_thread(...) so the loop stays free
        faces.detect()         -> Triton, the detector model
        faces.align()          -> warp 5 landmarks onto a fixed template
        faces.embed()          -> Triton, the recogniser model
      persons.insert_person()  -> MySQL. A duplicate id raises here.
      vectors.insert_vector()  -> Milvus. A failure deletes the MySQL row.
      cache.set_person()       -> Redis
    images.discard()   -> always remove the scratch file
```

## Async and threads

Two different problems need two different tools.

I/O waits use async drivers. `aiomysql`, `redis.asyncio` and `AsyncMilvusClient` all
release the event loop while they wait for a socket.

Face processing is not a wait. It is arithmetic in NumPy and OpenCV, and the process
is busy, not idle. An `async def` around it would still hold the loop, because a
coroutine only yields at an `await`. So `enroll.embed_face()` sends the whole
pipeline to a worker thread with `asyncio.to_thread`.

This is why `services/triton.py` keeps the synchronous gRPC client. It runs inside
that worker thread, and a worker thread has no event loop for an async client.

Measured on one image: the loop stays about 95% responsive with the thread, and 0%
without it.

## Data model

MySQL holds the person record. The `ID` column is the primary key, and it is the only
thing that decides whether an id is already taken.

Milvus holds one 512-value vector for each person, under the same id. The metric is
COSINE and the index is FLAT. FLAT is an exact search. It needs no training, unlike
IVF_FLAT, which needs roughly 160000 vectors before its clusters mean anything.

Redis caches the person record as JSON, with a time limit. JSON keeps the types
correct. A Redis hash would turn the id and the date into strings, so a cached read
and a database read would not agree.

The collection name comes from the recogniser name, for example
`faces_arcface_r50`. Two recognisers produce vectors of the same length that mean
different things. They must not share a collection. See [models.md](models.md).
