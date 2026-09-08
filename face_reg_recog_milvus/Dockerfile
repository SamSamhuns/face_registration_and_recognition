# FastAPI service. Triton lives in its own image (Dockerfile.triton).
FROM python:3.12-slim

LABEL maintainer="fname.lname@domain.com"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# opencv-python-headless still links against glib even without the GUI backends
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# `app` must sit *inside* WORKDIR so that `uvicorn app.server:app` (which puts the
# cwd on sys.path) can import it as a package.
WORKDIR /srv

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/cache /data/person_images /data/logs \
    && chown -R appuser:appuser /srv /data
USER appuser

EXPOSE 8080
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8080"]
