"""ORM model registry. The `Base` declarative root lives here so future
changes can attach their tables and Alembic's `target_metadata` keeps
pointing at one place. Importing this package registers every table on
`Base.metadata`, which is what the Alembic env relies on."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from yasli.models.types import (  # noqa: E402
    DISTRICT_CODE_VALUES,
    LOCALITY_TYPE_VALUES,
    DistrictCode,
    KIND_VALUES,
    Kind,
    LocalityType,
)
from yasli.models.institution import Institution  # noqa: E402
from yasli.models.street import Street  # noqa: E402
from yasli.models.address import Address, address_institutions  # noqa: E402
from yasli.models.grao_address import GraoAddress  # noqa: E402
from yasli.models.settlement import Settlement  # noqa: E402

__all__ = [
    "Base",
    "Kind",
    "KIND_VALUES",
    "DistrictCode",
    "DISTRICT_CODE_VALUES",
    "LocalityType",
    "LOCALITY_TYPE_VALUES",
    "Institution",
    "Street",
    "Address",
    "address_institutions",
    "GraoAddress",
    "Settlement",
]
