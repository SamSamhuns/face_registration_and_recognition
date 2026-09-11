# Face Registration and Recognition

[![tests](https://github.com/SamSamhuns/face_registration_and_recognition_milvus/actions/workflows/main_test.yml/badge.svg)](https://github.com/SamSamhuns/face_registration_and_recognition_milvus/actions/workflows/main_test.yml)
![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=for-the-badge&logo=docker&logoColor=white)![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)

Register a person with a photograph of their face, then identify that person in a
later photograph.

The service detects a face, aligns it onto a fixed landmark template, and turns it
into a 512-value vector. Milvus searches those vectors, MariaDB holds the person
records, and Redis caches reads. NVIDIA Triton serves the models.

- **Three detectors and three recognisers**, chosen by environment variable
- **Landmark alignment**, which holds recognition accuracy when the head is tilted
- **Async throughout**, so one slow request does not block the others
- **REST API** with OpenAPI documentation at `/docs`

## Requirements

- Docker and Docker Compose v2.24 or newer
- Python 3.11 or newer, up to 3.14
- About 40 GB of free disk. The Triton image alone is 31 GB unpacked.

## Quick start

```bash
cd face_reg_recog_milvus

# 1. Create the environment file. Change the passwords before you expose any port.
cp .env.example .env

# 2. Download the model weights, about 880 MB, verified by checksum.
python3 scripts/download_models.py

# 3. Start every service.
docker compose up -d
```

Then register a face and find it again:

```bash
curl -X POST http://localhost:8080/api/v1/persons \
  -F id=1 -F name=alice -F birthdate=1990-01-01 -F country=NP \
  -F image=@face.jpg

curl -X POST http://localhost:8080/api/v1/recognitions -F image=@probe.jpg
```

Interactive documentation is at <http://localhost:8080/docs>. Check that the service
can reach its dependencies with `curl http://localhost:8080/health/ready`.

## Documentation

| Document | Contents |
| --- | --- |
| [docs/README.md](docs/README.md) | Quick start, ports, tests, and lint |
| [docs/architecture.md](docs/architecture.md) | Services, code layers, and the path of one request |
| [docs/api.md](docs/api.md) | HTTP endpoints, status codes, and examples |
| [docs/models.md](docs/models.md) | Face models, downloads, and how to change them |
| [docs/security.md](docs/security.md) | Attacks on face recognition, and countermeasures |

## Tests

```bash
cd face_reg_recog_milvus
docker compose run --rm pytest
```

## Acknowledgements

- [milvus](https://milvus.io/)
- [triton-server](https://developer.nvidia.com/nvidia-triton-inference-server)
- [InsightFace](https://github.com/deepinsight/insightface)
- [OpenCV Zoo](https://github.com/opencv/opencv_zoo)
- [mariadb](https://mariadb.org/)
- [redis](https://redis.io/)
- [uvicorn](https://www.uvicorn.org/)
- [fastapi](https://fastapi.tiangolo.com/)
- [Pyfhel](https://pyfhel.readthedocs.io/en/latest/index.html)
