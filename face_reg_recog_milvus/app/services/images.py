"""
Getting image bytes onto local disk safely.

Both entry points (a multipart upload and a remote URL) land here, so the size and
type limits are enforced in one place instead of being duplicated per route -- or,
as before, not enforced at all.
"""

import ipaddress
import logging
import socket
import uuid
from pathlib import Path
from urllib.parse import urlparse

import aiofiles
import httpx
from fastapi import UploadFile

from app.config import (
    ALLOWED_IMAGE_TYPES,
    DOWNLOAD_CACHE_PATH,
    DOWNLOAD_TIMEOUT_SECONDS,
    MAX_DOWNLOAD_BYTES,
    MAX_UPLOAD_BYTES,
)
from app.errors import ImageSourceError, PayloadTooLargeError, UnsupportedMediaTypeError

logger = logging.getLogger("services.images")

CHUNK = 64 * 1024


def _scratch_path() -> Path:
    return Path(DOWNLOAD_CACHE_PATH) / f"{uuid.uuid4()}.jpg"


async def save_upload(upload: UploadFile) -> Path:
    """
    Stream an uploaded file to a scratch path, within the type and size limits.

    The upload is read in parts, not in one call. Reading it whole would hold the
    entire file in memory before any limit could apply, so a few large uploads would
    exhaust it. Reading in parts allows an early stop.

    A rejected upload deletes its partial file. Without that, a caller can fill the
    disk with rejected uploads, and the size limit becomes the attack it should stop.

    The content type is a hint, not proof. The client supplies it. It is a cheap
    early reject that saves a Triton round trip. The real check happens later, when
    faces.read_image() either decodes the bytes or fails.
    """
    if upload.content_type not in ALLOWED_IMAGE_TYPES:
        raise UnsupportedMediaTypeError(f"declared content-type {upload.content_type!r} is not an accepted image type")
    path, total = _scratch_path(), 0
    async with aiofiles.open(path, "wb") as fptr:
        while chunk := await upload.read(CHUNK):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                path.unlink(missing_ok=True)  # remove the partial file
                raise PayloadTooLargeError(f"upload exceeded {MAX_UPLOAD_BYTES} bytes")
            await fptr.write(chunk)
    return path


def _reject_private_host(url: str) -> None:
    """
    Refuse URLs that resolve to a private or loopback address.

    Without this, `image_url` is a server-side request forgery primitive: a caller
    can point it at 169.254.169.254 to read cloud instance metadata, or at
    http://redis-server:6379 to probe services on our own compose network. Note
    this is a best-effort check -- it still races DNS re-resolution between here
    and the actual request (a TOCTOU hole), which is why the download is also
    capped and time-limited below.
    """
    host = urlparse(url).hostname
    if not host:
        raise ImageSourceError("image_url has no host")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as excep:
        raise ImageSourceError(f"could not resolve host {host!r}") from excep
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            raise ImageSourceError(f"image_url resolves to a non-public address ({addr})")


async def save_from_url(url: str) -> Path:
    """Download a remote image to a scratch path, size- and time-limited."""
    _reject_private_host(url)
    path, total = _scratch_path(), 0
    try:
        async with (
            httpx.AsyncClient(follow_redirects=True, timeout=DOWNLOAD_TIMEOUT_SECONDS) as client,
            client.stream("GET", url) as response,
        ):
            response.raise_for_status()
            declared = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
            if declared and declared not in ALLOWED_IMAGE_TYPES:
                raise UnsupportedMediaTypeError(f"remote content-type {declared!r} is not an accepted image type")
            async with aiofiles.open(path, "wb") as fptr:
                async for chunk in response.aiter_bytes(CHUNK):
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise PayloadTooLargeError(f"remote image exceeded {MAX_DOWNLOAD_BYTES} bytes")
                    await fptr.write(chunk)
    except (UnsupportedMediaTypeError, PayloadTooLargeError):
        path.unlink(missing_ok=True)
        raise
    except httpx.HTTPError as excep:
        path.unlink(missing_ok=True)
        raise ImageSourceError(f"could not fetch image from {url}: {excep}") from excep
    return path


def discard(path: Path | None) -> None:
    """Remove a scratch file. Safe to call with None or an already-deleted path."""
    if path is not None:
        Path(path).unlink(missing_ok=True)
