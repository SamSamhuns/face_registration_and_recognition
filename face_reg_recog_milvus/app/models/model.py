"""
data models for fastapi+uvicorn server
"""

from datetime import date

from pydantic import BaseModel


class PersonModel(BaseModel):
    """
    Person data model. Based on the person table schema
    id: int = must be a unique id in the database, required
    name: str = name of person, required
    birthdate: str = date with format YYYY-MM-DD, required
    country: str = country, required
    city: str = city, optional
    title: str = person's title, optional
    org: str = person's org, optional
    """

    ID: int
    name: str
    birthdate: date
    country: str
    city: str = ""
    title: str = ""
    org: str = ""
