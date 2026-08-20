"""Every contract schema this app models, checked against the contract itself.

Field names, required sets and enum values are compared to
`packages/contracts/openapi.yaml`. Types are not — a mismatch there surfaces as a normal
validation failure, whereas a renamed or dropped field is invisible until the caller breaks.

⚠️ The coverage test at the bottom is the point of this file, and it does double duty here:
it proves nothing was forgotten **and** that this app has not quietly grown a copy of a
caller-side schema it should never hold.
"""

from typing import Any, get_args

import pytest
from pydantic import BaseModel

from ai_engine.models import (
    Brief,
    BriefFillResponse,
    Character,
    ComicDraft,
    DraftGenerateRequest,
    DraftGenerateResponse,
    DraftPatch,
    DraftPatchEngineRequest,
    Error,
    ImageQuality,
    ImageRenderRequest,
    ImageSpec,
    NeedsInput,
    Panel,
    PanelRole,
    RefusalReason,
    SingleAdDraft,
)
from ai_engine.service_schemas import BriefFillRequest

MODELS: dict[str, type[BaseModel]] = {
    "Brief": Brief,
    "BriefFillRequest": BriefFillRequest,
    "BriefFillResponse": BriefFillResponse,
    "Character": Character,
    "ComicDraft": ComicDraft,
    "DraftGenerateRequest": DraftGenerateRequest,
    "DraftGenerateResponse": DraftGenerateResponse,
    "DraftPatch": DraftPatch,
    "DraftPatchEngineRequest": DraftPatchEngineRequest,
    "Error": Error,
    "ImageRenderRequest": ImageRenderRequest,
    "ImageSpec": ImageSpec,
    "NeedsInput": NeedsInput,
    "Panel": Panel,
    "SingleAdDraft": SingleAdDraft,
}

ENUMS: dict[str, Any] = {"ImageQuality": ImageQuality, "PanelRole": PanelRole}

SCALAR_ALIASES = {"AdPlan", "GuardrailApplied"}

COVERED_IN_TEST_COMMON = {"ErrorCode", "OutputType"}

DEFERRED: set[str] = set()
"""Nothing is deferred any more.

`DraftPatchEngineRequest` sat here while `POST /v1/draft:patch` was unserved. It moved to
`MODELS` on 2026-08-15 with the route — and `DraftPatch` / `PanelPatchMap` came out of
`NOT_OURS` at the same time, because the engine does receive them.
"""

ROOT_MODELS = {"PanelPatchMap"}
"""A `RootModel` — an index-keyed map with no named properties, so the field comparisons
below do not apply to it. `tests/models/test_patch.py` covers its key pattern instead."""

NOT_OURS = {
    "ArtStyle",
    "BriefMeta",
    "BriefPatch",
    "BriefPatchRequest",
    "DraftPatchRequest",
    "FieldMeta",
    "FinalizeAccepted",
    "Job",
    "JobResult",
    "JobStatus",
    "LoginRequest",
    "Me",
    "MessageMode",
    "Session",
    "SessionCreateRequest",
    "SessionState",
    "SessionSummary",
    "Template",
}
"""Caller-side schemas this service must never receive, and therefore never model.

⚠️ Not a to-do list. Sessions, jobs, auth and catalog belong to apps/backend; a copy here
would be a second definition with nothing to keep it honest, and `messageMode` in
particular is a decision the caller makes about its own session. Adding one of these makes
the coverage test fail on purpose — move it to `MODELS` only if the **contract** starts
sending it to this service.
"""


def _wire_names(model: type[BaseModel]) -> set[str]:
    return {field.alias or name for name, field in model.model_fields.items()}


def _required_wire_names(model: type[BaseModel]) -> set[str]:
    return {
        field.alias or name for name, field in model.model_fields.items() if field.is_required()
    }


@pytest.mark.parametrize("name", sorted(MODELS))
def test_fields_match_the_contract(name: str, contract_schemas: dict[str, Any]) -> None:
    assert _wire_names(MODELS[name]) == set(contract_schemas[name]["properties"]), name


@pytest.mark.parametrize("name", sorted(MODELS))
def test_required_matches_the_contract(name: str, contract_schemas: dict[str, Any]) -> None:
    expected = set(contract_schemas[name].get("required", []))
    assert _required_wire_names(MODELS[name]) == expected, name


@pytest.mark.parametrize("name", sorted(ENUMS))
def test_enum_values_match_the_contract(name: str, contract_schemas: dict[str, Any]) -> None:
    assert set(get_args(ENUMS[name])) == set(contract_schemas[name]["enum"]), name


def test_refusal_reason_matches_the_contract(contract_schemas: dict[str, Any]) -> None:
    """Inline in the contract — a property of `DraftGenerateResponse`, not a named schema."""
    schema = contract_schemas["DraftGenerateResponse"]["properties"]["refusalReason"]
    assert set(get_args(RefusalReason)) == set(schema["enum"])


def test_every_contract_schema_is_accounted_for(contract_schemas: dict[str, Any]) -> None:
    """No contract schema may be silently missing, and none may be silently added."""
    accounted = (
        set(MODELS)
        | set(ENUMS)
        | SCALAR_ALIASES
        | COVERED_IN_TEST_COMMON
        | DEFERRED
        | ROOT_MODELS
        | NOT_OURS
    )
    assert set(contract_schemas) == accounted
