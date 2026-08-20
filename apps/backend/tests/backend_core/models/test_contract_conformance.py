"""Every contract schema this app models, checked against the contract itself.

Field names, required sets and enum values are compared to
`packages/contracts/openapi.yaml`. Types are not — a mismatch there shows up as a normal
validation failure, whereas a renamed or dropped field is invisible until a client breaks.

⚠️ The coverage test at the bottom is the point of this file. Without it, forgetting a
schema is silent: the ones we did write still pass and nothing counts what is missing.
"""

from typing import Any, get_args

import pytest
from pydantic import BaseModel

from api.schemas import SessionCreateRequest
from backend_core.models import (
    ArtStyle,
    Brief,
    BriefFillResponse,
    BriefMeta,
    BriefPatch,
    BriefPatchRequest,
    Character,
    ComicDraft,
    DraftGenerateRequest,
    DraftGenerateResponse,
    DraftPatch,
    DraftPatchEngineRequest,
    DraftPatchRequest,
    Error,
    FieldMeta,
    FinalizeAccepted,
    ImageQuality,
    ImageRenderRequest,
    ImageSpec,
    Job,
    JobResult,
    JobStatus,
    LoginRequest,
    Me,
    NeedsInput,
    Panel,
    PanelRole,
    RefusalReason,
    Session,
    SessionState,
    SessionSummary,
    SingleAdDraft,
    Template,
)

MODELS: dict[str, type[BaseModel]] = {
    "ArtStyle": ArtStyle,
    "Brief": Brief,
    "BriefFillResponse": BriefFillResponse,
    "BriefMeta": BriefMeta,
    "BriefPatch": BriefPatch,
    "BriefPatchRequest": BriefPatchRequest,
    "Character": Character,
    "ComicDraft": ComicDraft,
    "DraftGenerateRequest": DraftGenerateRequest,
    "DraftGenerateResponse": DraftGenerateResponse,
    "DraftPatch": DraftPatch,
    "DraftPatchEngineRequest": DraftPatchEngineRequest,
    "DraftPatchRequest": DraftPatchRequest,
    "Error": Error,
    "FieldMeta": FieldMeta,
    "FinalizeAccepted": FinalizeAccepted,
    "ImageRenderRequest": ImageRenderRequest,
    "ImageSpec": ImageSpec,
    "Job": Job,
    "JobResult": JobResult,
    "LoginRequest": LoginRequest,
    "Me": Me,
    "NeedsInput": NeedsInput,
    "Panel": Panel,
    "Session": Session,
    "SessionCreateRequest": SessionCreateRequest,
    "SessionSummary": SessionSummary,
    "SingleAdDraft": SingleAdDraft,
    "Template": Template,
}

ENUMS: dict[str, Any] = {
    "ImageQuality": ImageQuality,
    "JobStatus": JobStatus,
    "PanelRole": PanelRole,
    "SessionState": SessionState,
}

SCALAR_ALIASES = {"AdPlan", "GuardrailApplied"}
"""Plain `str` / `bool` in the contract, so there is no class to compare field names on."""

COVERED_IN_TEST_COMMON = {"ErrorCode", "MessageMode", "OutputType"}

DEFERRED: set[str] = set()
"""Empty as of S5 — the patch family landed in `backend_core.models.patch`.

⚠️ Kept as an empty set rather than deleted. It is the mechanism that keeps "we deferred it"
and "we forgot it" distinguishable, and the next schema the contract grows ahead of the
implementation belongs in here rather than quietly missing from the coverage test.
"""

ROOT_MODELS = {"PanelPatchMap"}
"""A JSON object with no fixed keys, so `model_fields` is empty and there is nothing to
compare. Its key pattern and value shape are checked in test_patch.py instead."""

NOT_MODELLED = {"BriefFillRequest"}
"""Sent by this app as a multipart body it never receives, so there is nothing to validate.

Its receiving shape lives in apps/ai-engine.
"""


def _wire_names(model: type[BaseModel]) -> set[str]:
    return {field.alias or name for name, field in model.model_fields.items()}


def _required_wire_names(model: type[BaseModel]) -> set[str]:
    return {
        field.alias or name for name, field in model.model_fields.items() if field.is_required()
    }


@pytest.mark.parametrize("name", sorted(MODELS))
def test_fields_match_the_contract(name: str, contract_schemas: dict[str, Any]) -> None:
    schema = contract_schemas[name]
    assert _wire_names(MODELS[name]) == set(schema["properties"]), name


@pytest.mark.parametrize("name", sorted(MODELS))
def test_required_matches_the_contract(name: str, contract_schemas: dict[str, Any]) -> None:
    schema = contract_schemas[name]
    assert _required_wire_names(MODELS[name]) == set(schema.get("required", [])), name


@pytest.mark.parametrize("name", sorted(ENUMS))
def test_enum_values_match_the_contract(name: str, contract_schemas: dict[str, Any]) -> None:
    assert set(get_args(ENUMS[name])) == set(contract_schemas[name]["enum"]), name


def test_inline_enums_on_field_meta_match_the_contract(contract_schemas: dict[str, Any]) -> None:
    """`filledBy` and `visibility` are inline enums, so they need their own comparison."""
    properties = contract_schemas["FieldMeta"]["properties"]
    filled_by, visibility = (
        FieldMeta.model_fields["filled_by"],
        FieldMeta.model_fields["visibility"],
    )
    assert set(get_args(filled_by.annotation)) == set(properties["filledBy"]["enum"])
    assert set(get_args(visibility.annotation)) == set(properties["visibility"]["enum"])


def test_refusal_reason_matches_the_contract(contract_schemas: dict[str, Any]) -> None:
    """Also inline — it is a property of `DraftGenerateResponse`, not a named schema."""
    schema = contract_schemas["DraftGenerateResponse"]["properties"]["refusalReason"]
    assert set(get_args(RefusalReason)) == set(schema["enum"])


def test_brief_meta_mirrors_brief() -> None:
    """`BriefMeta` must carry exactly `Brief`'s keys.

    A brief field with no meta is a field the screen cannot decide whether to show as
    editable, and the contract states the two share key sets.
    """
    assert _wire_names(BriefMeta) == _wire_names(Brief)
    assert _required_wire_names(BriefMeta) == _required_wire_names(Brief)


def test_every_contract_schema_is_accounted_for(contract_schemas: dict[str, Any]) -> None:
    """No contract schema may be silently missing from this app.

    ⚠️ This is the test that makes the others trustworthy. Checking only the models we
    remembered to write proves nothing about the ones we forgot.
    """
    accounted = (
        set(MODELS)
        | set(ENUMS)
        | SCALAR_ALIASES
        | COVERED_IN_TEST_COMMON
        | DEFERRED
        | ROOT_MODELS
        | NOT_MODELLED
    )
    assert set(contract_schemas) == accounted
