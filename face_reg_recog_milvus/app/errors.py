"""
Domain errors and their HTTP representation.

Services raise these; a single handler registered in server.py turns them into
responses. Status code policy lives in one place, so a caller can tell "person not
found" from "milvus is down", and a failure never arrives as 200 with an error
message inside the body.

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

    An error with no entry becomes 500, not 400. An unmapped error is a fault in
    this map, and it must look like one.
    """
    return _STATUS_BY_ERROR.get(type(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)


# Built once at import, not per call: a wrong constant name then fails at import
# instead of on the first error response.
#
# Keep HTTP_413_REQUEST_ENTITY_TOO_LARGE. Starlette renamed it to
# HTTP_413_CONTENT_TOO_LARGE, but that spelling does not exist before Starlette 0.48,
# and fastapi 0.129 accepts a range of Starlette versions. Only this spelling works
# across all of them. Newer versions mark it deprecated, which is a warning, not a
# failure.
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
