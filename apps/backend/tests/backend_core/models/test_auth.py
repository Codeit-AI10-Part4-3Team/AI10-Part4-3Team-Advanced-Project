"""What the contract comparison cannot say about the auth schemas.

⚠️ Field names and required sets are **not** checked here — test_contract_conformance.py
compares every schema in this app against `openapi.yaml`, `LoginRequest` and `Me` included.
Repeating that here would give two places to update and one of them would be forgotten.

What is left is the part that has to survive a change to the contract itself, plus the
rejection behaviour of the login body.
"""

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from backend_core.models import LoginRequest, Me


def _wire_names(model: type[BaseModel]) -> set[str]:
    return {field.alias or name for name, field in model.model_fields.items()}


def test_me_carries_no_personal_data() -> None:
    """Pinned on purpose, and deliberately not derived from the contract.

    The conformance test would happily follow `openapi.yaml` if someone added an email to
    it. This one does not: every personal item on `Me` is another thing to hold, protect and
    delete (도메인_모델.md 2.1절), so adding one is a decision that has to be argued here
    first and in the contract second.
    """
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
