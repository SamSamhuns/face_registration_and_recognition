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
    Body of POST /persons, sent as multipart form fields beside the image.

    Form fields, not query parameters, so names and birthdates stay out of access
    logs and proxy traces.
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


class Box(BaseModel):
    """Face position in the original image, in pixels."""

    x1: int
    y1: int
    x2: int
    y2: int


class Match(BaseModel):
    """The closest registered person for one face."""

    person: PersonRead
    similarity: float = Field(description="cosine similarity in [-1, 1]; higher is closer")


class FaceResult(BaseModel):
    """One detected face, and who it is."""

    box: Box
    score: float = Field(description="detector confidence")
    matched: bool
    match: Match | None = None


class RecognitionResult(BaseModel):
    """
    Outcome of POST /recognitions.

    `faces` holds every face the detector found, best confidence first. A face with
    `matched: false` is a successful answer, not an error, so the whole reply is
    200 even when nobody is recognised.
    """

    faces: list[FaceResult]
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
