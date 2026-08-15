"""Partial replacement — what `POST /v1/draft:patch` receives.

Contract: packages/contracts/openapi.yaml. Edit it first (AGENTS.md 교체 순서).

⚠️ Only the **engine-side** half of the patch family lives here. `DraftPatchRequest`,
`BriefPatch` and `BriefPatchRequest` are the caller's own request bodies and this service
never sees them; modelling one would be a second definition with nothing keeping it honest
(tests/models/test_contract_conformance.py, `NOT_OURS`).

Two invariants are enforced by what these schemas **lack**:

- **INV-8** — `adPlan` is read-only, so `DraftPatch` has no `adPlan`.
- **INV-5** — `role` follows from `index`, so a panel patch has no `role`.

Naming either one is rejected by `extra="forbid"` as an unknown field, which the service
answers as a 422.
"""

from typing import Annotated, Self

from pydantic import Field, RootModel, model_validator

from ai_engine.models.brief import Brief, check_brief_matches_output_type
from ai_engine.models.common import Base, Omittable, OutputType
from ai_engine.models.draft import Draft, check_draft_matches_output_type

PanelIndex = Annotated[str, Field(pattern="^[1-6]$")]
"""Panel keys are the strings `"1"`..`"6"` — JSON object keys, so strings, not integers."""


class AtLeastOneField(Base):
    """A patch body that names nothing is not a request (`minProperties: 1`).

    ⚠️ Checked with `model_fields_set` rather than by looking for non-`None` values. In this
    family `""` is a legitimate instruction ("empty it") and `None` only ever means the key
    was absent, so testing values would collapse two opposite requests into one.
    """

    @model_validator(mode="after")
    def _at_least_one(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("patch must name at least one field; an empty patch changes nothing")
        return self


class PanelPatch(AtLeastOneField):
    """One cell's changeable parts.

    No `index` and no `role`: the key in `PanelPatchMap` is the index, and the role is
    derived from it (INV-5).
    """

    scene: Omittable[str] = None
    dialogue: Omittable[str] = None


class PanelPatchMap(RootModel[dict[PanelIndex, PanelPatch]]):
    """Contract: `components.schemas.PanelPatchMap`.

    ⚠️ **An index-keyed object, not an array**, and that only works because the comic is
    exactly six cells in fixed order (INV-1). Do not copy this shape to a collection whose
    order can change — the key would stop identifying the same thing between two reads.
    """


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


class DraftPatchEngineRequest(Base):
    """Contract: `components.schemas.DraftPatchEngineRequest`. Backend -> this service.

    Carries the whole draft alongside the patch: to change only the named parts the engine
    has to know what the rest is. It is still not asked to rewrite the whole thing — the
    patch says what moves, and everything outside it comes back unchanged.

    ⚠️ The pairing check is the same one `ImageRenderRequest` runs. A `single_ad` request
    carrying a `ComicDraft` is not a strange-but-workable input; it is a caller bug, and
    accepting it would have the engine patch panels onto an ad that has none.
    """

    output_type: OutputType
    brief: Brief
    draft: Draft
    patch: DraftPatch
    guardrail_applied: bool = True

    @model_validator(mode="after")
    def _check_pairing(self) -> Self:
        check_brief_matches_output_type(self.output_type, self.brief)
        check_draft_matches_output_type(self.output_type, self.draft)
        return self
