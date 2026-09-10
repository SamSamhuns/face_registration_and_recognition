"""
Request and response models.

Every endpoint declares a `response_model`, which does three jobs at once: it
validates what we send, it strips anything not declared (so an internal field can
never leak by accident), and it populates the OpenAPI schema at /docs. The old
routes returned bare dicts, so /docs told a client nothing about the shape of a
response.
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class PersonBase(BaseModel):
    """Fields shared by reads and writes."""

    name: str = Field(min_length=1, max_length=255)
    birthdate: date
    country: str = Field(min_length=1, max_length=255)
    city: str = Field(default="", max_length=255)
    title: str = Field(default="", max_length=255)
    org: str = Field(default="", max_length=255)


class PersonCreate(PersonBase):
    """
    Body of POST /persons, submitted as multipart form fields alongside the image.

    These used to travel as *query parameters*, which put names and birthdates into
    every access log and proxy trace along the way.
    """

    id: int = Field(description="caller-assigned unique person id")


class PersonRead(PersonBase):
    """A registered person as returned to clients."""

    id: int
    model_config = ConfigDict(from_attributes=True)


class PersonList(BaseModel):
    """A page of persons."""

    items: list[PersonRead]
    total: int
    limit: int
    offset: int


class Match(BaseModel):
    """The closest registered person for a probe image."""

    person: PersonRead
    similarity: float = Field(description="cosine similarity in [-1, 1]; higher is closer")


class RecognitionResult(BaseModel):
    """
    Outcome of POST /recognitions.

    `matched: false` is a successful request with a negative answer, so it is a 200
    and not an error. Only a request we could not process at all becomes non-2xx.
    """

    matched: bool
    match: Match | None = None
    detector: str
    recognizer: str


class ImageUrlBody(BaseModel):
    """Alternative to a file upload: fetch the image from a URL."""

    image_url: HttpUrl


class ErrorDetail(BaseModel):
    """Uniform error envelope for every non-2xx response."""

    error: str = Field(description="machine-readable error class, e.g. PersonNotFoundError")
    detail: str = Field(description="human-readable explanation")


class HealthStatus(BaseModel):
    """Liveness / readiness payload."""

    status: str
    dependencies: dict[str, str] = Field(default_factory=dict)
