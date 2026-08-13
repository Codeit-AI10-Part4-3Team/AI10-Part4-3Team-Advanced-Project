"""The auth schemas against the contract, field by field.

Same purpose as test_common.py: catch the moment `openapi.yaml` and these models stop
agreeing. A hand-copied schema drifts from the contract it is supposed to mirror, and the
drift is invisible until a client breaks.
"""

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from backend_core.models import LoginRequest, Me


def _wire_names(model: type[BaseModel]) -> set[str]:
    return {field.alias or name for name, field in model.model_fields.items()}


def _required_wire_names(model: type[BaseModel]) -> set[str]:
    return {
        field.alias or name for name, field in model.model_fields.items() if field.is_required()
    }


def test_login_request_matches_the_contract(contract_schemas: dict[str, Any]) -> None:
    schema = contract_schemas["LoginRequest"]
    assert _wire_names(LoginRequest) == set(schema["properties"])
    assert _required_wire_names(LoginRequest) == set(schema["required"])


def test_me_matches_the_contract(contract_schemas: dict[str, Any]) -> None:
    schema = contract_schemas["Me"]
    assert _wire_names(Me) == set(schema["properties"])
    assert _required_wire_names(Me) == set(schema["required"])


def test_me_carries_no_personal_data() -> None:
    """Pinned on purpose. The contract says no email and no display name, and the reason is
    that each one is another personal item to hold, protect and delete (도메인_모델.md 2.1절).
    Adding one is a decision, not a convenience — this test is where it has to be argued."""
    assert _wire_names(Me) == {"userId", "loginId", "createdAt"}


@pytest.mark.parametrize(
    "body",
    [
        {"loginId": "", "password": "x"},
        {"loginId": "demo1", "password": ""},
        {"loginId": "demo1"},
        {"password": "x"},
        {"loginId": "demo1", "password": "x", "remember": True},
    ],
    ids=["empty id", "empty password", "no password", "no id", "unknown field"],
)
def test_malformed_login_bodies_are_rejected(body: dict[str, Any]) -> None:
    """422 rather than a 401 with an empty string reaching argon2 — the contract separates
    "you sent nonsense" from "those credentials are wrong"."""
    with pytest.raises(ValidationError):
        LoginRequest.model_validate(body)
