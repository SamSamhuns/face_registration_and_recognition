"""
configurations and env variables load
"""

import os
from logging.config import dictConfig

from app.logging_config import LogConfig

# save directories
DOWNLOAD_CACHE_PATH = os.getenv("DOWNLOAD_CACHE_PATH", default="app/.data")
DOWNLOAD_IMAGE_PATH = os.getenv("DOWNLOAD_IMAGE_PATH", default="volumes/person_images")
LOG_STORAGE_PATH = os.getenv("LOG_STORAGE_PATH", default="volumes/server_logs")

os.makedirs(DOWNLOAD_CACHE_PATH, exist_ok=True)
os.makedirs(DOWNLOAD_IMAGE_PATH, exist_ok=True)
os.makedirs(LOG_STORAGE_PATH, exist_ok=True)

# logging conf
log_cfg = LogConfig()
# override info & error log paths
log_cfg.handlers["info_rotating_file_handler"]["filename"] = os.path.join(LOG_STORAGE_PATH, "info.log")
log_cfg.handlers["warning_file_handler"]["filename"] = os.path.join(LOG_STORAGE_PATH, "error.log")
log_cfg.handlers["error_file_handler"]["filename"] = os.path.join(LOG_STORAGE_PATH, "error.log")
dictConfig(log_cfg.model_dump())

# http api server
FASTAPI_SERVER_PORT = int(os.getenv("FASTAPI_SERVER_PORT", default="8080"))
API_V1_PREFIX = "/api/v1"

# --- OIDC, provided by Authentik -----------------------------------------------
# The API trusts exactly one issuer and one audience. Neither has a default, and the
# server refuses to start without the issuer: a default issuer would mean accepting
# tokens minted by somebody else's identity provider.
# Both are shown in Authentik under Applications -> Providers -> your OAuth2 provider.
OIDC_ISSUER = os.getenv("OIDC_ISSUER", default="")
OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID", default="")
# Where Authentik publishes the public half of its signing key. The discovery
# document puts it directly under the issuer; overridable for an odd deployment.
OIDC_JWKS_URL = os.getenv("OIDC_JWKS_URL", default=f"{OIDC_ISSUER.rstrip('/')}/jwks/" if OIDC_ISSUER else "")
# Authentik group names, as they arrive in the `groups` claim. These are the two
# roles this service has: an admin may change the registered population, an operator
# may only identify against it.
OIDC_ADMIN_GROUP = os.getenv("OIDC_ADMIN_GROUP", default="face-admin")
OIDC_OPERATOR_GROUP = os.getenv("OIDC_OPERATOR_GROUP", default="face-operator")

# CORS. Note allow_credentials=True is INVALID alongside a "*" origin -- browsers
# reject that combination -- so credentials are only enabled for an explicit list.
CORS_ALLOW_ORIGINS = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", default="*").split(",") if o.strip()]
CORS_ALLOW_CREDENTIALS = CORS_ALLOW_ORIGINS != ["*"]

# upload limits, enforced at the trust boundary before anything touches disk
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", default=str(10 * 1024 * 1024)))
ALLOWED_IMAGE_TYPES = frozenset({"image/jpeg", "image/jpg", "image/png", "image/webp", "image/bmp"})
# cap on bytes pulled from a remote image_url, so a hostile URL cannot fill the disk
MAX_DOWNLOAD_BYTES = int(os.getenv("MAX_DOWNLOAD_BYTES", default=str(10 * 1024 * 1024)))
DOWNLOAD_TIMEOUT_SECONDS = float(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", default="10"))

# triton server conf
TRITON_SERVER_HOST = os.getenv("TRITON_SERVER_HOST", default="0.0.0.0")
TRITON_SERVER_PORT = int(os.getenv("TRITON_SERVER_PORT", default="8081"))

# redis conf
REDIS_HOST = os.getenv("REDIS_HOST", default="0.0.0.0")
REDIS_PORT = int(os.getenv("REDIS_PORT", default="6379"))

# mysql conf
MYSQL_HOST = os.getenv("MYSQL_HOST", default="0.0.0.0")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", default="3306"))
MYSQL_USER = os.getenv("MYSQL_USER", default="user")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", default="pass")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", default="default")
MYSQL_PERSON_TABLE = os.getenv("MYSQL_PERSON_TABLE", default="person")
# table where ops will be run on
MYSQL_CUR_TABLE = os.getenv("MYSQL_CUR_TABLE", default=MYSQL_PERSON_TABLE)
# aiomysql pool bounds. A single shared connection is neither thread safe nor task
# safe, so each task takes one from the pool.
MYSQL_POOL_MIN = int(os.getenv("MYSQL_POOL_MIN", default="1"))
MYSQL_POOL_MAX = int(os.getenv("MYSQL_POOL_MAX", default="10"))

# how long a cached person record stays in redis
REDIS_CACHE_TTL_SECONDS = int(os.getenv("REDIS_CACHE_TTL_SECONDS", default="3600"))

# milvus conf
MILVUS_HOST = os.getenv("MILVUS_HOST", default="0.0.0.0")
MILVUS_PORT = int(os.getenv("MILVUS_PORT", default="19530"))

# face pipeline: exactly one detector and one recogniser are active per deployment.
# Swap them by changing the env var and restarting; see scripts/download_models.py
# for the full set of available models.
FACE_DETECTOR = os.getenv("FACE_DETECTOR", default="scrfd_10g")
FACE_RECOGNIZER = os.getenv("FACE_RECOGNIZER", default="arcface_r50")
# minimum detector confidence for a box to count as a face
FACE_DET_THRESHOLD = float(os.getenv("FACE_DET_THRESHOLD", default="0.5"))
# reject faces smaller than this fraction of the frame (0.001 == 0.1%)
FACE_MIN_AREA_FRACTION = float(os.getenv("FACE_MIN_AREA_FRACTION", default="0.001"))
# Upper bound on faces processed from one image. Each face costs an alignment, an
# embedding and a vector search, so a crowd photograph is a cheap way to load the
# service. Registration always needs exactly one face, whatever this is set to.
FACE_MAX_FACES = int(os.getenv("FACE_MAX_FACES", default="10"))

# every supported recogniser emits 512-d embeddings
FACE_VECTOR_DIM = 512
# app.services.faces.embed() L2-normalises every vector, so cosine is the metric that
# has meaning here. FLAT is an exact search. It needs no training, unlike IVF_FLAT,
# which needs roughly 160000 vectors before its clusters mean anything.
FACE_METRIC_TYPE = "COSINE"
FACE_INDEX_TYPE = "FLAT"
# Cosine similarity, from -1 to 1. A higher score is a better match.
FACE_MATCH_THRESHOLD = float(os.getenv("FACE_MATCH_THRESHOLD", default="0.4"))

# Embeddings from two different recognisers are NOT comparable even though they share
# a dimension -- each model learns its own vector space. So the collection name is
# derived from the recogniser: switching FACE_RECOGNIZER points at a different
# collection instead of silently matching new probes against stale vectors.
# Overridable so the test suite can point at a throwaway collection, the same way
# MYSQL_CUR_TABLE isolates the SQL side.
FACE_COLLECTION_NAME = os.getenv("FACE_COLLECTION_NAME", default=f"faces_{FACE_RECOGNIZER}")
