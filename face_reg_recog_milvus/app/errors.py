"""
Domain errors and their HTTP representation.

Services raise these; a single handler registered in server.py turns them into
responses. Keeping status-code policy in ONE place is the fix for the old design,
where every route wrapped everything in `except Exception` and raised a blanket
400 -- so "person not found" and "milvus is down" were indistinguishable to a
client, and genuine successes came back as 200 with {"status": "failed"} inside.

Note that app.services.faces deliberately does NOT import this module: it is a pure
face-processing service with no idea that HTTP exists. app.services.enroll
translates its FaceError family into the errors below. That is what keeps faces.py
reusable from a batch script or a notebook.
"""
from fastapi import status


class AppError(Exception):
    """Base for expected, client-visible failures."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# --- client sent something we cannot accept -------------------------------------
class ValidationError(AppError):
    """Input was structurally acceptable but semantically wrong."""


class UnsupportedMediaTypeError(AppError):
    """Upload was not an image type we accept."""


class PayloadTooLargeError(AppError):
    """Upload or download exceeded the configured byte cap."""


class InvalidImageError(AppError):
    """Bytes arrived but could not be decoded as an image."""


class ImageSourceError(AppError):
    """A supplied image_url could not be fetched, or was not allowed."""


# --- face pipeline outcomes ------------------------------------------------------
class NoFaceDetectedError(AppError):
    """No face passed the detector threshold."""


class MultipleFacesError(AppError):
    """More faces than the endpoint accepts."""


# --- resource state --------------------------------------------------------------
class PersonNotFoundError(AppError):
    """No person with that id."""


class PersonAlreadyExistsError(AppError):
    """A person with that id is already registered."""


# --- our fault, not theirs -------------------------------------------------------
class UpstreamUnavailableError(AppError):
    """Triton / Milvus / MySQL / Redis could not be reached."""


def status_for(exc: AppError) -> int:
    """
    Map a domain error onto the HTTP status code the client should see.

    TODO(human): implement this mapping.

    Return an int status code for each AppError subclass above. Use the
    `status.HTTP_*` constants imported at the top of this file rather than bare
    integers, so the intent reads at a glance.

    Things worth deciding deliberately:

      - PersonNotFoundError. 404 is the obvious answer.
      - PersonAlreadyExistsError. 409 CONFLICT says "the request is fine, but it
        clashes with current state" -- which is exactly a duplicate id. 400 would
        wrongly suggest the request itself was malformed.
      - NoFaceDetectedError / MultipleFacesError. These are the interesting ones.
        The upload was a perfectly valid image; it just did not contain what we
        need. 422 UNPROCESSABLE_ENTITY is the usual fit. Some APIs prefer 400.
        Pick one and be consistent -- but note FastAPI already uses 422 for
        request-schema failures, so consider whether overloading it obscures the
        difference between "your JSON was wrong" and "your photo had no face".
      - PayloadTooLargeError -> 413, UnsupportedMediaTypeError -> 415. These have
        purpose-built codes; use them.
      - InvalidImageError / ImageSourceError / ValidationError -> 400 territory.
      - UpstreamUnavailableError. This is the one that must NOT be a 4xx: a dead
        Milvus is not the client's fault. 503 SERVICE_UNAVAILABLE tells a caller
        (and any retry logic) that retrying later is reasonable.

    Anything unrecognised should fall back to 500 rather than silently becoming a
    400 -- an unmapped error is a bug in this function, and it should look like one.
    """
    return _STATUS_BY_ERROR.get(type(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)


# Built once at import, not per call: a wrong constant name then fails at import
# instead of on the first error response.
#
# Do not "modernise" HTTP_413_REQUEST_ENTITY_TOO_LARGE to HTTP_413_CONTENT_TOO_LARGE.
# The new name does not exist before Starlette ~0.48, and fastapi 0.129 accepts a
# range of Starlette versions, so only the old name works across all of them. It is
# deprecated in newer versions, which is a warning, not a failure.
_STATUS_BY_ERROR: dict[type[AppError], int] = {
    PersonNotFoundError: status.HTTP_404_NOT_FOUND,
    PersonAlreadyExistsError: status.HTTP_409_CONFLICT,
    NoFaceDetectedError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    MultipleFacesError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    PayloadTooLargeError: status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    UnsupportedMediaTypeError: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    InvalidImageError: status.HTTP_400_BAD_REQUEST,
    ImageSourceError: status.HTTP_400_BAD_REQUEST,
    ValidationError: status.HTTP_400_BAD_REQUEST,
    UpstreamUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
}
