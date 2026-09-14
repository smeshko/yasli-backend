"""Pydantic models defining the v2 snapshot contract — vendored from
`yasli/scraper/src/yasli_scraper/models.py`. The two copies must stay
byte-for-byte equivalent in their generated JSON Schema; the drift test in
`tests/snapshot_contract/test_schema_match.py` enforces that.

The contact fields (`phone`, `email`, `director`, `website`) were added here
first: this copy is intentionally one phase ahead of the scraper until it
starts emitting them (scraper epic 01, phase 1.1), because both sides validate with
`extra="forbid"` and the backend must accept the fields before they arrive.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationInfo,
    field_validator,
    field_serializer,
    model_validator,
)
from pydantic.networks import UrlConstraints

HttpsUrl = Annotated[HttpUrl, UrlConstraints(allowed_schemes=["https"])]
DistrictCode = Literal["01", "02", "03", "04", "05"]
Kind = Literal["nursery", "kindergarten", "preschool"]


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
    kind: Kind
    source_url: HttpsUrl
    address_entries: list[AddressEntry]
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    director: str | None = None
    website: str | None = None
    district_code: DistrictCode | None = None
    has_infant_group: bool

    @field_validator("address", "phone", "email", "director", "website")
    @classmethod
    def _optional_strings_non_empty(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        if value == "":
            raise ValueError(f"{info.field_name} must be non-empty or null")
        return value

    @model_validator(mode="after")
    def _nursery_requires_district(self) -> Self:
        if self.kind == "nursery" and self.district_code is None:
            raise ValueError("nursery institutions require district_code")
        return self


class Snapshot(BaseModel):
    """The top-level v2 snapshot envelope written to R2."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2]
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
