"""Domain error to HTTP status mapping. Pure unit tests: no services needed."""

import pytest
from app import errors
from fastapi import status


@pytest.mark.parametrize(
    ("error_class", "expected"),
    [
        (errors.PersonNotFoundError, status.HTTP_404_NOT_FOUND),
        (errors.PersonAlreadyExistsError, status.HTTP_409_CONFLICT),
        (errors.NoFaceDetectedError, status.HTTP_422_UNPROCESSABLE_ENTITY),
        (errors.MultipleFacesError, status.HTTP_422_UNPROCESSABLE_ENTITY),
        (errors.PayloadTooLargeError, status.HTTP_413_CONTENT_TOO_LARGE),
        (errors.UnsupportedMediaTypeError, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE),
        (errors.InvalidImageError, status.HTTP_400_BAD_REQUEST),
        (errors.ImageSourceError, status.HTTP_400_BAD_REQUEST),
        (errors.ValidationError, status.HTTP_400_BAD_REQUEST),
        (errors.UpstreamUnavailableError, status.HTTP_503_SERVICE_UNAVAILABLE),
    ],
)
def test_status_for_known_errors(error_class, expected):
    assert errors.status_for(error_class("boom")) == expected


def test_unmapped_error_is_500():
    """An error with no entry is a bug in the mapping. It must not look like a 400."""
    assert errors.status_for(errors.AppError("boom")) == status.HTTP_500_INTERNAL_SERVER_ERROR


def test_every_error_class_is_mapped():
    """Guard against adding a new AppError subclass and forgetting the mapping."""
    subclasses = {
        cls
        for cls in vars(errors).values()
        if isinstance(cls, type) and issubclass(cls, errors.AppError) and cls is not errors.AppError
    }
    missing = sorted(cls.__name__ for cls in subclasses if cls not in errors._STATUS_BY_ERROR)
    assert not missing, f"unmapped error classes: {missing}"
