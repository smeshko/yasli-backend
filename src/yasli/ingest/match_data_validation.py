"""Read-only validation for match-routing data assumptions."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from yasli.models import Address, Institution, Settlement, address_institutions
from yasli.models.types import DISTRICT_CODE_VALUES, KIND_VALUES

VARNA_CITY_SETTLEMENT_CODE = "10135"


@dataclass(frozen=True)
class AddressSummary:
    total: int
    district_known: int
    settlement_known_no_district: int
    no_settlement_no_district: int
    unknown_settlement_codes: int
    invalid_district_codes: int


@dataclass(frozen=True)
class SettlementSummary:
    city: int
    village: int


@dataclass(frozen=True)
class InstitutionSummary:
    nursery: int
    kindergarten: int
    preschool: int
    infant_group_kindergartens: int
    invalid_kinds: int
    nursery_without_district: int


@dataclass(frozen=True)
class CoverageEdgeSummary:
    kindergarten: int
    preschool: int
    nursery: int


@dataclass(frozen=True)
class WarningCounts:
    varna_city_without_district: int
    zero_infant_group_kindergartens: int
    zero_kindergarten_edges: int
    zero_preschool_edges: int

    @property
    def total(self) -> int:
        return (
            self.varna_city_without_district
            + self.zero_infant_group_kindergartens
            + self.zero_kindergarten_edges
            + self.zero_preschool_edges
        )


@dataclass(frozen=True)
class HardFailureCounts:
    no_settlement_no_district_addresses: int
    unknown_settlement_codes: int
    nursery_without_district: int
    nursery_coverage_edges: int
    invalid_institution_kinds: int
    invalid_address_district_codes: int

    @property
    def total(self) -> int:
        return (
            self.no_settlement_no_district_addresses
            + self.unknown_settlement_codes
            + self.nursery_without_district
            + self.nursery_coverage_edges
            + self.invalid_institution_kinds
            + self.invalid_address_district_codes
        )


@dataclass(frozen=True)
class MatchDataValidationResult:
    addresses: AddressSummary
    settlements: SettlementSummary
    institutions: InstitutionSummary
    coverage_edges: CoverageEdgeSummary
    warnings: WarningCounts
    hard_failures: HardFailureCounts

    @property
    def has_hard_failures(self) -> bool:
        return self.hard_failures.total > 0


def validate_match_data(session: Session) -> MatchDataValidationResult:
    """Return structured match-data validation counts for ``session``."""

    addresses = _collect_address_summary(session)
    settlements = _collect_settlement_summary(session)
    institutions = _collect_institution_summary(session)
    coverage_edges = _collect_coverage_edge_summary(session)
    warnings = WarningCounts(
        varna_city_without_district=_count_varna_city_without_district(session),
        zero_infant_group_kindergartens=int(
            institutions.infant_group_kindergartens == 0
        ),
        zero_kindergarten_edges=int(coverage_edges.kindergarten == 0),
        zero_preschool_edges=int(coverage_edges.preschool == 0),
    )
    hard_failures = HardFailureCounts(
        no_settlement_no_district_addresses=addresses.no_settlement_no_district,
        unknown_settlement_codes=addresses.unknown_settlement_codes,
        nursery_without_district=institutions.nursery_without_district,
        nursery_coverage_edges=coverage_edges.nursery,
        invalid_institution_kinds=institutions.invalid_kinds,
        invalid_address_district_codes=addresses.invalid_district_codes,
    )

    return MatchDataValidationResult(
        addresses=addresses,
        settlements=settlements,
        institutions=institutions,
        coverage_edges=coverage_edges,
        warnings=warnings,
        hard_failures=hard_failures,
    )


def format_match_data_validation_result(result: MatchDataValidationResult) -> str:
    """Format validation output for operator-facing CLI use."""

    status = (
        "match data validation failed"
        if result.has_hard_failures
        else "match data validation ok"
    )
    lines = [
        status,
        "addresses={"
        f"total:{result.addresses.total},"
        f"district_known:{result.addresses.district_known},"
        f"settlement_known_no_district:"
        f"{result.addresses.settlement_known_no_district},"
        f"no_settlement_no_district:{result.addresses.no_settlement_no_district},"
        f"invalid_district_codes:{result.addresses.invalid_district_codes}"
        "}",
        "settlements={"
        f"city:{result.settlements.city},"
        f"village:{result.settlements.village},"
        f"unknown_codes:{result.addresses.unknown_settlement_codes}"
        "}",
        "institutions={"
        f"nursery:{result.institutions.nursery},"
        f"kindergarten:{result.institutions.kindergarten},"
        f"preschool:{result.institutions.preschool},"
        f"infant_group_kindergartens:"
        f"{result.institutions.infant_group_kindergartens},"
        f"invalid_kinds:{result.institutions.invalid_kinds},"
        f"nursery_without_district:{result.institutions.nursery_without_district}"
        "}",
        "coverage_edges={"
        f"kindergarten:{result.coverage_edges.kindergarten},"
        f"preschool:{result.coverage_edges.preschool},"
        f"nursery:{result.coverage_edges.nursery}"
        "}",
        "warnings={"
        f"varna_city_without_district:"
        f"{result.warnings.varna_city_without_district},"
        f"zero_infant_group_kindergartens:"
        f"{result.warnings.zero_infant_group_kindergartens},"
        f"zero_kindergarten_edges:{result.warnings.zero_kindergarten_edges},"
        f"zero_preschool_edges:{result.warnings.zero_preschool_edges}"
        "}",
    ]
    if result.has_hard_failures:
        lines.append(
            "failures={"
            "no_settlement_no_district_addresses:"
            f"{result.hard_failures.no_settlement_no_district_addresses},"
            f"unknown_settlement_codes:"
            f"{result.hard_failures.unknown_settlement_codes},"
            f"nursery_without_district:"
            f"{result.hard_failures.nursery_without_district},"
            f"nursery_coverage_edges:{result.hard_failures.nursery_coverage_edges},"
            f"invalid_institution_kinds:"
            f"{result.hard_failures.invalid_institution_kinds},"
            f"invalid_address_district_codes:"
            f"{result.hard_failures.invalid_address_district_codes}"
            "}"
        )
    return "\n".join(lines)


def _collect_address_summary(session: Session) -> AddressSummary:
    total = _scalar_count(session, select(func.count()).select_from(Address))
    district_known = _scalar_count(
        session,
        select(func.count()).select_from(Address).where(Address.district_code.is_not(None)),
    )
    settlement_known_no_district = _scalar_count(
        session,
        select(func.count())
        .select_from(Address)
        .where(
            Address.district_code.is_(None),
            Address.settlement_code.is_not(None),
        ),
    )
    no_settlement_no_district = _scalar_count(
        session,
        select(func.count())
        .select_from(Address)
        .where(
            Address.district_code.is_(None),
            Address.settlement_code.is_(None),
        ),
    )
    unknown_settlement_codes = _scalar_count(
        session,
        select(func.count(func.distinct(Address.settlement_code)))
        .select_from(Address)
        .outerjoin(Settlement, Address.settlement_code == Settlement.code)
        .where(
            Address.settlement_code.is_not(None),
            Settlement.code.is_(None),
        ),
    )
    invalid_district_codes = _scalar_count(
        session,
        select(func.count())
        .select_from(Address)
        .where(
            Address.district_code.is_not(None),
            ~Address.district_code.in_(DISTRICT_CODE_VALUES),
        ),
    )
    return AddressSummary(
        total=total,
        district_known=district_known,
        settlement_known_no_district=settlement_known_no_district,
        no_settlement_no_district=no_settlement_no_district,
        unknown_settlement_codes=unknown_settlement_codes,
        invalid_district_codes=invalid_district_codes,
    )


def _collect_settlement_summary(session: Session) -> SettlementSummary:
    counts = dict(
        session.execute(
            select(Settlement.locality_type, func.count())
            .select_from(Settlement)
            .group_by(Settlement.locality_type)
        ).all()
    )
    return SettlementSummary(
        city=int(counts.get("city", 0)),
        village=int(counts.get("village", 0)),
    )


def _collect_institution_summary(session: Session) -> InstitutionSummary:
    kind_counts = dict(
        session.execute(
            select(Institution.kind, func.count())
            .select_from(Institution)
            .where(Institution.kind.in_(KIND_VALUES))
            .group_by(Institution.kind)
        ).all()
    )
    infant_group_kindergartens = _scalar_count(
        session,
        select(func.count())
        .select_from(Institution)
        .where(
            Institution.kind == "kindergarten",
            Institution.has_infant_group.is_(True),
        ),
    )
    invalid_kinds = _scalar_count(
        session,
        select(func.count())
        .select_from(Institution)
        .where(
            or_(
                Institution.kind.is_(None),
                ~Institution.kind.in_(KIND_VALUES),
            )
        ),
    )
    nursery_without_district = _scalar_count(
        session,
        select(func.count())
        .select_from(Institution)
        .where(
            Institution.kind == "nursery",
            Institution.district_code.is_(None),
        ),
    )
    return InstitutionSummary(
        nursery=int(kind_counts.get("nursery", 0)),
        kindergarten=int(kind_counts.get("kindergarten", 0)),
        preschool=int(kind_counts.get("preschool", 0)),
        infant_group_kindergartens=infant_group_kindergartens,
        invalid_kinds=invalid_kinds,
        nursery_without_district=nursery_without_district,
    )


def _collect_coverage_edge_summary(session: Session) -> CoverageEdgeSummary:
    counts = dict(
        session.execute(
            select(Institution.kind, func.count())
            .select_from(
                address_institutions.join(
                    Institution,
                    address_institutions.c.institution_id == Institution.id,
                )
            )
            .where(Institution.kind.in_(KIND_VALUES))
            .group_by(Institution.kind)
        ).all()
    )
    return CoverageEdgeSummary(
        kindergarten=int(counts.get("kindergarten", 0)),
        preschool=int(counts.get("preschool", 0)),
        nursery=int(counts.get("nursery", 0)),
    )


def _count_varna_city_without_district(session: Session) -> int:
    return _scalar_count(
        session,
        select(func.count())
        .select_from(Address)
        .where(
            Address.district_code.is_(None),
            Address.settlement_code == VARNA_CITY_SETTLEMENT_CODE,
        ),
    )


def _scalar_count(session: Session, statement) -> int:
    value = session.scalar(statement)
    return int(value or 0)
