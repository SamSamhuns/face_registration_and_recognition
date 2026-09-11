# Documentation

| Document | Contents |
| --- | --- |
| [architecture.md](architecture.md) | Services, code layers, and the path of one request |
| [api.md](api.md) | HTTP endpoints, status codes, and examples |
| [models.md](models.md) | Face models, how to download them, and how to change them |
| [frontend.md](frontend.md) | The web pages, HTTPS, and the nginx proxy |
| [security.md](security.md) | Attacks on face recognition, and countermeasures |

## Quick start

You need Docker and Docker Compose. All commands run from the `face_reg_recog_milvus`
directory.

```bash
cd face_reg_recog_milvus

# 1. Create the environment file. Change the passwords before you expose any port.
cp .env.example .env

# 2. Download the model weights. This writes into the Triton model repository.
python3 scripts/download_models.py

# 3. Start every service.
docker compose up -d
```

The API is then at `http://localhost:8080`. Interactive documentation is at
`http://localhost:8080/docs`.

Check that the service can reach its dependencies:

```bash
curl http://localhost:8080/health/ready
```

## Ports

The host ports come from `.env`. These are the defaults.

| Port | Service | Purpose |
| --- | --- | --- |
| 8443 | frontend | The web pages, over HTTPS |
| 8080 | api | The HTTP API |
| 8001 | triton | Inference, gRPC |
| 19530 | standalone | Milvus, vector search |
| 3306 | mysql | Person records |
| 6379 | redis-server | Read cache |
| 3000 | attu | Milvus web console |
| 8081 | mysql-admin | phpMyAdmin |

Triton also serves HTTP on port 8000 inside the network. That port is not published.
The container healthcheck uses it.

## Disk

The stack needs roughly 40 GB of images. Triton is almost all of it.

| Image | Size |
| --- | --- |
| `nvcr.io/nvidia/tritonserver` | 31 GB |
| `python:3.12` (test runner) | 1.6 GB |
| `milvusdb/milvus` | 1.3 GB |
| everything else together | 3 GB |
| model weights plus download cache | 1.8 GB |

Two consequences:

- A GitHub-hosted runner cannot run the test job. It offers about 14 GB free, and
  the Triton image alone is larger than that. Use a self-hosted runner.
- On a self-hosted runner the Docker build cache grows without limit. The workflow
  prunes anything older than a week after each run.

The API image excludes the model weights through `.dockerignore`. Triton reads them
from a bind mount, so the API never needs a copy. Without that exclusion the image
grows by about 1.9 GB, and a `chown -R` after the copy would double it again.

`app/.model_cache` holds the downloaded archives so a repeat download is cheap. It is
safe to delete at any time.

## Tests

The suite needs the data services and Triton to be running. It creates a throwaway
SQL table and a throwaway Milvus collection, and it removes both afterwards.

```bash
# In Docker, the same way CI runs it:
docker compose run --rm pytest

# Or against a local virtual environment:
python -m pytest tests
```

A local run reads its host names from the process environment, not from `.env`.
Export them first, or the defaults will point at the wrong hosts.

## Lint

```bash
ruff check .          # report problems
ruff check . --fix    # correct what can be corrected automatically
```

Use `ruff check` without `--fix` in CI. The automatic fixer removes an import that a
bug has made unused, which hides the bug.
