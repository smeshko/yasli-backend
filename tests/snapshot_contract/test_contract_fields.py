"""Contract tests for the optional contact fields on `Institution`."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from yasli.snapshot_contract import Snapshot
from yasli.snapshot_contract.models import Institution

CONTACT_FIELDS = ("phone", "email", "director", "website")
NULLABLE_STRING_FIELDS = ("address", *CONTACT_FIELDS)


def _institution(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "external_id": "42",
        "name": "ДГ № 42",
        "kind": "kindergarten",
        "source_url": "https://dg.uslugi.io/lv/childhood",
        "address_entries": [{"street": "УЛ. ОПЪЛЧЕНСКА", "number": "12"}],
        "has_infant_group": False,
    }
    payload.update(overrides)
    return payload


def _snapshot(*institutions: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "scraped_at": "2026-09-13T01:02:04Z",
        "city": "varna",
        "institutions": list(institutions),
    }


def test_contacts_absent_parse_to_none() -> None:
    snapshot = Snapshot.model_validate(_snapshot(_institution()))

    inst = snapshot.institutions[0]
    for field in CONTACT_FIELDS:
        assert getattr(inst, field) is None


def test_contacts_present_round_trip_verbatim() -> None:
    contacts = {
        "phone": "052 123 456 / 0888 123 456 / 052 654 321",
        "email": "dg42@varna.bg",
        "director": "Мария Иванова Петрова",
        "website": "https://dg42.example.bg",
    }

    snapshot = Snapshot.model_validate(_snapshot(_institution(**contacts)))

    inst = snapshot.institutions[0]
    for field, value in contacts.items():
        assert getattr(inst, field) == value


@pytest.mark.parametrize("field", NULLABLE_STRING_FIELDS)
def test_empty_string_is_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match=f"{field} must be non-empty or null"):
        Institution.model_validate(_institution(**{field: ""}))


def test_unknown_field_still_forbidden() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Institution.model_validate(_institution(fax="052 000 000"))
