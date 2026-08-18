"""Partial replacement — the patch family (S5 부분 교체).

Contract: packages/contracts/openapi.yaml. Edit it first (AGENTS.md 교체 순서).

⚠️ **Only the fields being changed are sent.** The client does not return the whole
document, because then the server would not be keeping the original — the client would, and
a bug in a screen would silently overwrite a brief nobody asked to change.

⚠️ That makes "absent" load-bearing here in a way it is nowhere else: **an omitted key means
"leave it alone", and `""` means "empty it".** Everywhere else in this contract absence and
emptiness are close enough to blur; here they are opposite instructions, and `exclude_unset`
is the only correct way to read one of these models.

Three invariants are enforced by the *shape* of these schemas rather than by a check:

- **INV-4** — `panelCount` is `hidden`, so it has no field here to be named in.
- **INV-5** — `role` follows `index`; `PanelPatch` has no `role`.
- **INV-8** — `adPlan` is read-only; `DraftPatch` has no `adPlan`.

Naming one of them is rejected by `extra="forbid"` as an unknown field, which is a 422
`INVALID_REQUEST` — the contract's answer.
"""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import Field, RootModel, model_validator

from backend_core.models.brief import Brief, Character
from backend_core.models.common import Base, Omittable, OutputType
from backend_core.models.draft import Draft

PanelIndex = Annotated[str, Field(pattern="^[1-6]$")]
"""Panel keys are the strings `"1"`..`"6"` — JSON object keys, so strings, not integers."""


class AtLeastOneField(Base):
    """A patch body that names nothing is not a request (`minProperties: 1`).

    ⚠️ Enforced because an empty patch is not harmless. It applies no change and still
    **increments `revision`**, which is the value every other open screen is holding: one
    no-op request invalidates their optimistic lock and their next real edit comes back 409
    for no reason anyone can see.

    Checked with `model_fields_set` rather than by looking for non-`None` values, because in
    this family `""` is a legitimate instruction ("empty it") and `None` only ever means the
    key was absent.
    """

    @model_validator(mode="after")
    def _at_least_one(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("patch must name at least one field; an empty patch changes nothing")
        return self


class PanelPatch(AtLeastOneField):
    """One cell's changeable parts.

    No `index` and no `role`: the key in `PanelPatchMap` is the index, and `role` is derived
    from it (INV-5). The six-beat structure is the planning rationale, so a request that
    could reorder it would discard the reason the format exists.
    """

    scene: Omittable[str] = None
    dialogue: Omittable[str] = None


class PanelPatchMap(RootModel[dict[PanelIndex, PanelPatch]]):
    """Panels addressed by index key, e.g. `{"4": {"dialogue": "..."}}`.

    ⚠️ An object keyed by index rather than an array, and that only works **because a comic
    is exactly six panels and they never reorder** (INV-1). Do not copy this convention to a
    collection whose order can change — there the key would stop identifying the same item
    between two requests.
    """

    root: dict[PanelIndex, PanelPatch] = Field(min_length=1)


class BriefPatch(AtLeastOneField):
    """Contract: `components.schemas.BriefPatch`. At least one field.

    ⚠️ **No `productImageUrl`.** 도메인_모델 3절 marks it `editable`, but no re-upload path
    was ever decided, so the contract deliberately leaves no place to send one. Opening it
    means this endpoint has to accept multipart, which changes this schema's shape — so the
    contract changes first, not this file.
    """

    product_name: Omittable[Annotated[str, Field(min_length=1, max_length=40)]] = None
    selling_point: Omittable[Annotated[str, Field(min_length=1, max_length=200)]] = None
    note: Omittable[Annotated[str, Field(max_length=500)]] = None
    category: Omittable[str] = None
    target: Omittable[str] = None
    art_style: Omittable[str] = None
    character: Omittable[Character] = None
    aspect_ratio: Omittable[str] = None


class DraftPatch(AtLeastOneField):
    """Contract: `components.schemas.DraftPatch`. At least one field.

    ⚠️ No `adPlan` (INV-8) and no `role` (INV-5), and their absence is the enforcement. To
    change the plan you change the brief and regenerate: leaving both editable produces a
    draft whose plan and brief say different things, and nothing decides which is true.
    """

    panels: Omittable[PanelPatchMap] = None
    # ⚠️ Python name only. The wire name is the contract's `copy`; using `copy` as the
    # attribute would shadow `BaseModel.copy()` (same reason as `SingleAdDraft.ad_copy`).
    ad_copy: Omittable[str] = Field(default=None, alias="copy")
    visual_plan: Omittable[str] = None


_PATCH_FIELDS_BY_OUTPUT_TYPE: dict[OutputType, dict[str, str]] = {
    # attribute -> wire name, for the fields the *other* output type owns.
    "single_ad": {"panels": "panels"},
    "comic": {"ad_copy": "copy", "visual_plan": "visualPlan"},
}


def check_patch_matches_output_type(output_type: OutputType, patch: DraftPatch) -> None:
    """Reject a patch that names fields the output type does not have.

    The sibling of `check_brief_matches_output_type`, and needed for the same reason:
    `DraftPatch` carries every output type's fields and cannot know which one the session
    is, so a client following the contract can still send a mismatched patch.

    ⚠️ **The mismatch is invisible without this, not loud.** `single_ad` with a `panels`
    patch satisfies `minProperties: 1`, and the engine's stub drops `panels` on its way to a
    single-ad draft — so the round trip is a 200 whose draft never changed. Worse when the
    patch also names `copy`: the copy changes, the panels instruction is gone, and the
    screen reads it as success (2026-08-18 실측).

    ⚠️ Reads `model_fields_set`, not the values: in this family `""` is a real instruction
    and `None` only ever means the key was absent.
    """
    for attribute, wire_name in _PATCH_FIELDS_BY_OUTPUT_TYPE[output_type].items():
        if attribute in patch.model_fields_set:
            raise ValueError(f"{wire_name} does not apply to {output_type} output; omit the key")


class BriefPatchRequest(Base):
    """Contract: `components.schemas.BriefPatchRequest`.

    ⚠️ `revision` is a **body field, not an `If-Match` header**, and that was a decision
    (the contract records it). An `ETag` round trip would have the server emit one, the
    client store it and send it back — for two endpoints, when `revision` is already in the
    response body they just read.
    """

    revision: int = Field(ge=0)
    patch: BriefPatch


class DraftPatchRequest(Base):
    """Contract: `components.schemas.DraftPatchRequest`. See `BriefPatchRequest` on
    `revision`."""

    revision: int = Field(ge=0)
    patch: DraftPatch


class DraftPatchEngineRequest(Base):
    """Contract: `components.schemas.DraftPatchEngineRequest`. Backend -> ai-engine.

    Carries the whole draft alongside the patch: to change only the named parts the engine
    has to know what the rest is. It is still not asked to rewrite the whole thing — the
    patch says what moves, and everything outside it comes back unchanged.
    """

    output_type: OutputType
    brief: Brief
    draft: Draft
    patch: DraftPatch
    guardrail_applied: bool = True
