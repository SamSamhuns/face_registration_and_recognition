# Documentation

| Document | Contents |
| --- | --- |
| [architecture.md](architecture.md) | Services, code layers, and the path of one request |
| [api.md](api.md) | HTTP endpoints, status codes, and examples |
| [models.md](models.md) | Face models, how to download them, and how to change them |

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
| 8080 | api | The HTTP API |
| 8001 | triton | Inference, gRPC |
| 19530 | standalone | Milvus, vector search |
| 3306 | mysql | Person records |
| 6379 | redis-server | Read cache |
| 3000 | attu | Milvus web console |
| 8081 | mysql-admin | phpMyAdmin |

Triton also serves HTTP on port 8000 inside the network. That port is not published.
The container healthcheck uses it.

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
