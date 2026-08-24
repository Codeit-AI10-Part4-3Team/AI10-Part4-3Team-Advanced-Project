"""The internal paths this service serves for apps/backend.

Contract: packages/contracts/openapi.yaml, `generation` tag. Edit it first (AGENTS.md
교체 순서).

⚠️ These paths have **no authentication**. Not exposing them is the defence, which is why
`infra/docker-compose.yml` binds this service to `127.0.0.1:8100` — and, since the VPC's
firewall is shared with other teams and outside our control, that binding is the only
defence we actually hold (infra/README.md).

`BriefFillRequest` is not here: it is `multipart/form-data`, so it names an uploaded file
and lives in `ai_engine.service_schemas` to keep this package importable without a web
framework — the eval harness reaches these modules directly.
"""

from typing import Literal

from pydantic import Field, model_validator

from ai_engine.models.brief import Brief, NeedsInput, check_brief_matches_output_type
from ai_engine.models.common import Base, Omittable, OutputType
from ai_engine.models.draft import Draft, check_draft_matches_output_type

GuardrailApplied = bool
"""Contract: `components.schemas.GuardrailApplied`. Default `true`.

In a request it asks for the guardrail; in a response it states whether one ran.

⚠️ **`false` is a control run.** It splits the numerator from the denominator of the
reported hallucination-suppression rate, so bypassing the guardrail to make a test pass
does not fix the test — it voids the measurement.
"""

RefusalReason = Literal["no_evidence", "guardrail"]
"""Contract: `components.schemas.DraftGenerateResponse.refusalReason`.

`guardrail` means an unsupported claim survived **one regeneration**. The first violation is
retried silently here and never reaches the caller.
"""


class BriefFillResponse(Base):
    """Contract: `components.schemas.BriefFillResponse`.

    Not deciding is not an error. When inference cannot settle on a category or target this
    returns 200 with `needsInput`, and `category`/`target` are empty strings.

    ⚠️ **The absence of this response is the caller's degraded path** (ADR-0005). Do not add
    a field to signal it — an outage cannot be reported by the response that never arrived.
    """

    category: str
    target: str
    needs_input: Omittable[NeedsInput] = None


class DraftGenerateRequest(Base):
    """Contract: `components.schemas.DraftGenerateRequest`.

    ⚠️ The evidence for the guardrail is `brief.sellingPoint` plus `brief.note` plus
    `brief.product_name` (생성_파이프라인 5.2절, added 2026-08-20 so a copy that echoes the
    product name is not counted as an invented claim). `category` and `target` are inferred
    values and are **not** evidence — grounding a claim in them means grounding it in
    something the model made up.
    """

    output_type: OutputType
    brief: Brief
    guardrail_applied: GuardrailApplied = True

    @model_validator(mode="after")
    def _check_brief(self) -> "DraftGenerateRequest":
        check_brief_matches_output_type(self.output_type, self.brief)
        return self


class DraftGenerateResponse(Base):
    """Contract: `components.schemas.DraftGenerateResponse`.

    ⚠️ **Omitting `draft` is a normal 200** — it means we could have written something and
    declined to invent it. Never assemble copy from rules when the model call fails; that is
    precisely the path that emits claims the input never made.

    `guardrailApplied` is always present, refusal or not.
    """

    draft: Omittable[Draft] = None
    guardrail_applied: GuardrailApplied
    refusal_reason: Omittable[RefusalReason] = None


class ImageSpec(Base):
    """Contract: `components.schemas.ImageSpec`.

    ⚠️ **The caller sends the spec; this service never derives it** from the output type.
    Deriving it here would put 기획서 10.2's numbers in two places, and the two would part
    ways the first time one side changed.
    """

    width: int = Field(ge=16, le=3840, multiple_of=16)
    height: int = Field(ge=16, le=3840, multiple_of=16)


ImageQuality = Literal["low", "medium", "high"]
"""Contract: `components.schemas.ImageQuality`. Sent by the caller, never derived here.

The tier is fixed per output type — comic `medium`, single ad `low` (생성_파이프라인 6.2절).
Deriving it from `output_type` in this service would put the same decision in two places, for
exactly the reason `ImageSpec` is not derived either.

⚠️ The vendor's `auto` is deliberately absent: leaving the tier to the model swings the cost
of an identical request by up to 9x (2026-08-13, 08-15 실측). `high` is in the enum but has
never been measured — the per-call slowdown under parallel fan-out grows with the tier
(`low` 44%, `medium` 64%), so adopting it reopens 미결정_대장 N19-a.
"""


class ImageRenderRequest(Base):
    """Contract: `components.schemas.ImageRenderRequest`.

    Returns image bytes (lossless WebP), not JSON. Lossless because the comic has Korean
    dialogue drawn into it and 검증 1순위 scores those glyphs — scoring a lossy image measures
    compression artefacts instead of the model's rendering accuracy.

    ⚠️ This response shape may change: if dialogue moves to the fallback plan (speech
    bubbles drawn empty, text composited) the output becomes image + coordinates, and if
    panel-boundary control fails it becomes six images (미결정_대장 18.1 #1, #2).
    """

    output_type: OutputType
    brief: Brief
    draft: Draft
    spec: ImageSpec
    quality: ImageQuality

    @model_validator(mode="after")
    def _check_pairing(self) -> "ImageRenderRequest":
        check_brief_matches_output_type(self.output_type, self.brief)
        check_draft_matches_output_type(self.output_type, self.draft)
        return self
