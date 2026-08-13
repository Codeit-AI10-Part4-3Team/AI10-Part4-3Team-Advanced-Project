"""What this app sends to, and receives from, apps/ai-engine.

Contract: packages/contracts/openapi.yaml, `generation` tag. Edit it first (AGENTS.md
교체 순서).

⚠️ These are the **only** coupling between the two apps, and it is an HTTP one. Never
`import ai_engine` to reuse its copies of these — that single line removes the property the
repo's structure exists to prove (AGENTS.md 아키텍처 경계).

`BriefFillRequest` is absent on purpose: it is `multipart/form-data`, and this side builds
that body directly rather than modelling an upload it never receives. The receiving shape
lives in apps/ai-engine.
"""

from typing import Literal

from pydantic import Field, model_validator

from backend_core.models.brief import Brief, NeedsInput, check_brief_matches_output_type
from backend_core.models.common import Base, Omittable, OutputType
from backend_core.models.draft import Draft, check_draft_matches_output_type

GuardrailApplied = bool
"""Contract: `components.schemas.GuardrailApplied`. Default `true`.

⚠️ **`false` is a control run.** This value splits the numerator from the denominator of the
reported hallucination-suppression rate, so replacing the guardrail with a mock to make a
test pass does not fix the test — it voids the measurement. Never send `false` in
production.
"""

RefusalReason = Literal["no_evidence", "guardrail"]
"""Contract: `components.schemas.DraftGenerateResponse.refusalReason`.

`guardrail` means an unsupported claim survived **one regeneration**; the first violation is
retried silently inside the engine and never reaches the caller.
"""


class BriefFillResponse(Base):
    """Contract: `components.schemas.BriefFillResponse`.

    ⚠️ `needsInput` present means inference ran and could not decide — `category` and
    `target` are then empty strings and the session waits in `brief_filling`.

    **The absence of this response is the degraded path**, not a field in it. When the call
    fails or overruns 15s the caller skips auto-fill and proceeds with `messageMode:
    degraded`, still in `brief_filling` — moving straight to `brief_ready` would let draft
    generation start with two empty fields (ADR-0005).
    """

    category: str
    target: str
    needs_input: Omittable[NeedsInput] = None


class DraftGenerateRequest(Base):
    """Contract: `components.schemas.DraftGenerateRequest`."""

    output_type: OutputType
    brief: Brief
    guardrail_applied: GuardrailApplied = True

    @model_validator(mode="after")
    def _check_brief(self) -> "DraftGenerateRequest":
        check_brief_matches_output_type(self.output_type, self.brief)
        return self


class DraftGenerateResponse(Base):
    """Contract: `components.schemas.DraftGenerateResponse`.

    ⚠️ **A missing `draft` is a normal 200**, not an error: the engine could have written
    something and declined to invent it. `refusalReason` is present in that case.

    `guardrailApplied` is always present, refusal or not. If a control run and a verified
    output are indistinguishable, the suppression rate cannot be computed at all.
    """

    draft: Omittable[Draft] = None
    guardrail_applied: GuardrailApplied
    refusal_reason: Omittable[RefusalReason] = None


class ImageSpec(Base):
    """Contract: `components.schemas.ImageSpec`.

    Model limits (`gpt-image-2`): long edge 3840px, both sides multiples of 16, about
    8.29MP total. Comic is fixed at 3456 x 2304 (1152 per cell); the single-ad pixel size is
    still open (미결정_대장 18.1 #8).

    ⚠️ **The caller decides the spec.** If the engine picked it from the output type, 기획서
    10.2's numbers would exist in two places and drift the first time one side changed.
    """

    width: int = Field(ge=16, le=3840, multiple_of=16)
    height: int = Field(ge=16, le=3840, multiple_of=16)


class ImageRenderRequest(Base):
    """Contract: `components.schemas.ImageRenderRequest`.

    Only a finalized draft arrives here, once per session — that is the cost defence
    (INV-3). The response is image bytes (lossless WebP), not JSON.
    """

    output_type: OutputType
    brief: Brief
    draft: Draft
    spec: ImageSpec

    @model_validator(mode="after")
    def _check_pairing(self) -> "ImageRenderRequest":
        check_brief_matches_output_type(self.output_type, self.brief)
        check_draft_matches_output_type(self.output_type, self.draft)
        return self
