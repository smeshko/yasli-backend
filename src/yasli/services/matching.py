"""Shared address-to-institution matching logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from yasli.models.address import Address, address_institutions
from yasli.models.institution import Institution
from yasli.models.settlement import Settlement
from yasli.models.types import DistrictCode, Kind, LocalityType

MatchBasis = Literal["address", "district"]
Offering = Literal["standard", "infant_group"]

_RECEPTION_KIND_ORDER: dict[Kind, int] = {
    "nursery": 0,
    "kindergarten": 1,
    "preschool": 2,
}


@dataclass(frozen=True)
class SettlementContext:
    code: str
    name: str
    locality_type: LocalityType


@dataclass(frozen=True)
class AddressContext:
    id: int
    district_code: DistrictCode | None
    settlement_code: str | None
    settlement: SettlementContext | None


@dataclass(frozen=True)
class MatchedInstitution:
    id: int
    external_id: str
    name: str
    institution_kind: Kind
    source_url: str
    match_basis: MatchBasis
    has_infant_group: bool


@dataclass(frozen=True)
class MatchSet:
    address: AddressContext
    requested_kinds: tuple[Kind, ...]
    results: tuple[MatchedInstitution, ...]


@dataclass(frozen=True)
class MatchedOffering:
    id: int
    external_id: str
    name: str
    institution_kind: Kind
    reception_kind: Kind
    offering: Offering
    source_url: str
    match_basis: MatchBasis
    has_infant_group: bool


def _standard_offering(row: MatchedInstitution) -> MatchedOffering:
    return MatchedOffering(
        id=row.id,
        external_id=row.external_id,
        name=row.name,
        institution_kind=row.institution_kind,
        reception_kind=row.institution_kind,
        offering="standard",
        source_url=row.source_url,
        match_basis=row.match_basis,
        has_infant_group=row.has_infant_group,
    )


def _infant_group_offering(row: MatchedInstitution) -> MatchedOffering:
    return MatchedOffering(
        id=row.id,
        external_id=row.external_id,
        name=row.name,
        institution_kind=row.institution_kind,
        reception_kind="nursery",
        offering="infant_group",
        source_url=row.source_url,
        match_basis=row.match_basis,
        has_infant_group=row.has_infant_group,
    )


def _expand(row: MatchedInstitution) -> list[MatchedOffering]:
    offerings = [_standard_offering(row)]
    if (
        row.institution_kind == "kindergarten"
        and row.has_infant_group
        and row.match_basis == "address"
    ):
        offerings.append(_infant_group_offering(row))
    return offerings


def _offering_sort_key(o: MatchedOffering) -> tuple[int, str, Kind, str]:
    return (
        _RECEPTION_KIND_ORDER[o.reception_kind],
        o.name,
        o.institution_kind,
        o.offering,
    )


def build_offerings(match_set: MatchSet) -> tuple[MatchedOffering, ...]:
    """Expand kindergartens-with-infant-group + apply canonical sort."""
    offerings = [o for row in match_set.results for o in _expand(row)]
    offerings.sort(key=_offering_sort_key)
    return tuple(offerings)


def effective_kinds(kind: Kind | None) -> tuple[Kind, ...]:
    if kind is None:
        return ("nursery", "kindergarten", "preschool")
    return (kind,)


def find_matches(
    session: Session, address_id: int, kind: Kind | None = None
) -> MatchSet | None:
    address = _address_context(session, address_id)
    if address is None:
        return None

    requested = effective_kinds(kind)
    results: list[MatchedInstitution] = []

    if "kindergarten" in requested:
        results.extend(_address_rows(session, address_id, "kindergarten"))
    if "nursery" in requested and address.district_code is not None:
        results.extend(
            _district_rows_for_kind(session, address.district_code, "nursery")
        )
    if "preschool" in requested:
        results.extend(_preschool_rows(session, address_id, address.district_code))

    return MatchSet(address=address, requested_kinds=requested, results=tuple(results))


def _address_context(session: Session, address_id: int) -> AddressContext | None:
    stmt = (
        select(
            Address.id,
            Address.district_code,
            Address.settlement_code,
            Settlement.code.label("settlement_ref_code"),
            Settlement.name.label("settlement_name"),
            Settlement.locality_type.label("settlement_locality_type"),
        )
        .outerjoin(Settlement, Address.settlement_code == Settlement.code)
        .where(Address.id == address_id)
        .limit(1)
    )
    row = session.execute(stmt).first()
    if row is None:
        return None

    settlement = None
    if row.settlement_ref_code is not None:
        settlement = SettlementContext(
            code=row.settlement_ref_code,
            name=row.settlement_name,
            locality_type=row.settlement_locality_type,
        )

    return AddressContext(
        id=row.id,
        district_code=row.district_code,
        settlement_code=row.settlement_code,
        settlement=settlement,
    )


def _address_rows(
    session: Session, address_id: int, kind: Kind
) -> list[MatchedInstitution]:
    stmt = (
        select(
            Institution.id,
            Institution.external_id,
            Institution.name,
            Institution.kind,
            Institution.source_url,
            Institution.has_infant_group,
        )
        .join(
            address_institutions,
            Institution.id == address_institutions.c.institution_id,
        )
        .where(address_institutions.c.address_id == address_id)
        .where(Institution.kind == kind)
    )
    return [
        MatchedInstitution(
            id=row.id,
            external_id=row.external_id,
            name=row.name,
            institution_kind=row.kind,
            source_url=row.source_url,
            match_basis="address",
            has_infant_group=row.has_infant_group,
        )
        for row in session.execute(stmt).all()
    ]


def _district_rows_for_kind(
    session: Session, district_code: DistrictCode, kind: Kind
) -> list[MatchedInstitution]:
    stmt = (
        select(
            Institution.id,
            Institution.external_id,
            Institution.name,
            Institution.kind,
            Institution.source_url,
            Institution.has_infant_group,
        )
        .where(Institution.kind == kind)
        .where(Institution.district_code == district_code)
        .where(Institution.district_code.is_not(None))
    )
    return [
        MatchedInstitution(
            id=row.id,
            external_id=row.external_id,
            name=row.name,
            institution_kind=row.kind,
            source_url=row.source_url,
            match_basis="district",
            has_infant_group=row.has_infant_group,
        )
        for row in session.execute(stmt).all()
    ]


def _preschool_rows(
    session: Session, address_id: int, district_code: DistrictCode | None
) -> list[MatchedInstitution]:
    address_rows = _address_rows(session, address_id, "preschool")
    if address_rows:
        return address_rows
    if district_code is None:
        return []
    return _district_rows_for_kind(session, district_code, "preschool")
