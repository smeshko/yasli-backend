"""Pydantic models defining the v1 snapshot contract — vendored from
`yasli/scraper/src/yasli_scraper/models.py`. The two copies must stay
byte-for-byte equivalent in their generated JSON Schema; the drift test in
`tests/snapshot_contract/test_schema_match.py` enforces that.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_serializer,
)
from pydantic.networks import UrlConstraints

HttpsUrl = Annotated[HttpUrl, UrlConstraints(allowed_schemes=["https"])]


class AddressEntry(BaseModel):
    """One street/number row attached to an institution.

    Both fields are preserved verbatim from the source — the scraper does not
    canonicalise. Normalisation is the backend's job during ingest.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    street: str = Field(min_length=1)
    number: str = Field(min_length=1)


class Institution(BaseModel):
    """One municipal institution (nursery / kindergarten / preschool)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    external_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: Literal["nursery", "kindergarten", "preschool"]
    source_url: HttpsUrl
    address_entries: list[AddressEntry]


class Snapshot(BaseModel):
    """The top-level v1 snapshot envelope written to R2."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    scraped_at: AwareDatetime
    city: str = Field(min_length=1)
    institutions: list[Institution]

    @field_serializer("scraped_at")
    def _serialise_scraped_at(self, value: datetime) -> str:
        return (
            value.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
