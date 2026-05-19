"""Service-layer tests for `build_offerings` (expansion + canonical ordering)."""

from __future__ import annotations

from yasli.services.matching import (
    AddressContext,
    MatchedInstitution,
    MatchSet,
    build_offerings,
)


def _address() -> AddressContext:
    return AddressContext(
        id=1,
        district_code="01",
        settlement_code=None,
        settlement=None,
    )


def _row(
    *,
    id: int,
    external_id: str,
    name: str,
    institution_kind: str,
    match_basis: str = "address",
    has_infant_group: bool = False,
    source_url: str = "https://example.test/",
) -> MatchedInstitution:
    return MatchedInstitution(
        id=id,
        external_id=external_id,
        name=name,
        institution_kind=institution_kind,  # type: ignore[arg-type]
        source_url=source_url,
        match_basis=match_basis,  # type: ignore[arg-type]
        has_infant_group=has_infant_group,
    )


def _match_set(*rows: MatchedInstitution) -> MatchSet:
    return MatchSet(
        address=_address(),
        requested_kinds=("nursery", "kindergarten", "preschool"),
        results=rows,
    )


def test_kindergarten_with_infant_group_expands_into_two_offerings() -> None:
    rows = _match_set(
        _row(
            id=4,
            external_id="K1",
            name="Kindergarten",
            institution_kind="kindergarten",
            has_infant_group=True,
            match_basis="address",
        ),
    )
    offerings = build_offerings(rows)

    keys = [(o.external_id, o.reception_kind, o.offering) for o in offerings]
    assert keys == [
        ("K1", "nursery", "infant_group"),
        ("K1", "kindergarten", "standard"),
    ]


def test_kindergarten_without_infant_group_emits_only_kindergarten_reception() -> None:
    rows = _match_set(
        _row(
            id=5,
            external_id="K2",
            name="Kindergarten Two",
            institution_kind="kindergarten",
            has_infant_group=False,
            match_basis="address",
        ),
    )
    offerings = build_offerings(rows)

    assert [
        (o.external_id, o.institution_kind, o.reception_kind, o.offering) for o in offerings
    ] == [("K2", "kindergarten", "kindergarten", "standard")]


def test_infant_group_expansion_requires_address_match_basis() -> None:
    """A kindergarten only emits an infant-group offering for address
    matches; a district-fallback kindergarten must not surface as a
    nursery row."""
    rows = _match_set(
        _row(
            id=6,
            external_id="K3",
            name="Kindergarten District",
            institution_kind="kindergarten",
            has_infant_group=True,
            match_basis="district",
        ),
    )
    offerings = build_offerings(rows)

    assert [(o.reception_kind, o.offering) for o in offerings] == [
        ("kindergarten", "standard"),
    ]


def test_ordering_is_reception_kind_then_name() -> None:
    rows = _match_set(
        _row(
            id=4,
            external_id="K1",
            name="Kindergarten",
            institution_kind="kindergarten",
            has_infant_group=True,
            match_basis="address",
        ),
        _row(
            id=1,
            external_id="N1",
            name="Nursery Odessa",
            institution_kind="nursery",
            match_basis="district",
        ),
        _row(
            id=7,
            external_id="P2",
            name="Preschool Primorski",
            institution_kind="preschool",
            match_basis="address",
        ),
    )
    offerings = build_offerings(rows)

    kind_order = {"nursery": 0, "kindergarten": 1, "preschool": 2}
    keys = [(o.reception_kind, o.name, o.institution_kind, o.offering) for o in offerings]
    assert keys == sorted(
        keys,
        key=lambda item: (kind_order[item[0]], item[1], item[2], item[3]),
    )


def test_offerings_have_stable_composite_identity() -> None:
    rows = _match_set(
        _row(
            id=4,
            external_id="K1",
            name="Kindergarten",
            institution_kind="kindergarten",
            has_infant_group=True,
            match_basis="address",
        ),
        _row(
            id=1,
            external_id="N1",
            name="Nursery",
            institution_kind="nursery",
            match_basis="district",
        ),
    )
    offerings = build_offerings(rows)

    keys = [(o.reception_kind, o.institution_kind, o.offering, o.id) for o in offerings]
    assert len(keys) == len(set(keys))


def test_build_offerings_is_deterministic() -> None:
    rows = _match_set(
        _row(
            id=4,
            external_id="K1",
            name="Kindergarten",
            institution_kind="kindergarten",
            has_infant_group=True,
            match_basis="address",
        ),
        _row(
            id=1,
            external_id="N1",
            name="Nursery",
            institution_kind="nursery",
            match_basis="district",
        ),
    )

    assert build_offerings(rows) == build_offerings(rows)
