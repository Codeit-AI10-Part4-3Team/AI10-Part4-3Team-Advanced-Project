"""Draft — the text proposal the user reviews before anything is drawn.

Contract: packages/contracts/openapi.yaml. Edit it first (AGENTS.md 교체 순서).

⚠️ Drafts carry **text only**. An image path or a preview here would break "nothing is
drawn before the user confirms", which is the cost defence for the whole flow (INV-3).
"""

from typing import Literal

from pydantic import Field

from ai_engine.models.common import Base, OutputType

AdPlan = str
"""Contract: `components.schemas.AdPlan`. One narrative paragraph, **read-only** (INV-8).

It overlaps the brief on purpose. To change it you change the brief and regenerate — making
both editable produces a draft whose plan and brief say different things.
"""


PanelRole = Literal["hook", "setup", "problem", "solution", "proof", "cta"]
"""Contract: `components.schemas.PanelRole`. One-to-one with 기획서 7.3's six beats.

⚠️ `index` decides `role`; the user never picks it (INV-5). The six-beat structure is the
planning rationale, so letting it be reordered discards the reason the format exists.
"""


class Panel(Base):
    """Contract: `components.schemas.Panel`. One comic cell."""

    index: int = Field(ge=1, le=6, description="읽는 순서. 3x2 배치 위치와 1:1")
    role: PanelRole
    scene: str
    dialogue: str = Field(
        description="길이 상한 없음. 한국어 렌더링 검증 결과에 종속됩니다 (미결정_대장 18.1 #1)"
    )


class ComicDraft(Base):
    """Contract: `components.schemas.ComicDraft`. Exactly six panels — 0 and 7 are both
    invalid (INV-1).

    ⚠️ No length cap on `dialogue`, and that is not an oversight. The contract left it open
    until the Korean-rendering trial lands; inventing one here would put a second source of
    truth next to the contract.
    """

    ad_plan: AdPlan
    panels: list[Panel] = Field(min_length=6, max_length=6)


class SingleAdDraft(Base):
    """Contract: `components.schemas.SingleAdDraft`.

    No panels, so the unit of partial replacement is a whole field rather than a cell.
    """

    ad_plan: AdPlan
    ad_copy: str = Field(
        alias="copy",
        description=(
            "⚠️ 파이썬 이름만 다릅니다. 와이어 이름은 계약대로 `copy` 이고 alias 로 고정했습니다. "
            "`copy` 를 그대로 쓰면 pydantic 의 BaseModel.copy() 를 가려 UserWarning 과 mypy "
            "오류가 나고, 무엇보다 draft.copy 가 문자열이라 .copy() 를 부르는 코드가 런타임에 "
            "깨집니다"
        ),
    )
    visual_plan: str


Draft = ComicDraft | SingleAdDraft
"""The contract's `oneOf` for a draft.

⚠️ **There is no discriminator field inside either model.** They are told apart by shape —
`panels` versus `copy`/`visualPlan` — which only works because `Base` forbids unknown
fields. The real discriminator lives outside, on the session's `outputType`, so anything
holding both must check the pairing (`check_draft_matches_output_type`).
"""


def check_draft_matches_output_type(output_type: OutputType, draft: Draft) -> None:
    """Reject a draft whose shape contradicts the declared output type.

    Without this, `outputType: "comic"` carrying a `SingleAdDraft` validates cleanly: the
    union accepts either member and nothing compares them. Raises `ValueError` so callers
    can surface it from a `model_validator` as a 422.
    """
    expected = ComicDraft if output_type == "comic" else SingleAdDraft
    if not isinstance(draft, expected):
        raise ValueError(
            f"draft is {type(draft).__name__} but outputType is {output_type!r}; "
            f"expected {expected.__name__}"
        )
