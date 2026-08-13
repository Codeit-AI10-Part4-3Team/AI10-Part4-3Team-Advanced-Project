"""Brief — the user's input plus whatever the engine could infer from it.

Contract: packages/contracts/openapi.yaml. Edit it first (AGENTS.md 교체 순서); the
conformance tests in tests/models/ fail if this file drifts from it.

⚠️ `BriefMeta` and `FieldMeta` are **not** here, and that is not an omission. They describe
who filled each value and whether the screen may edit it — a caller concern. The internal
`generation` paths only ever carry `brief` itself, and copying schemas this app never
receives would create drift with nothing to catch it.
"""

from pydantic import Field

from ai_engine.models.common import Base, Omittable, OutputType


class Character(Base):
    """Contract: `components.schemas.Character`. Comic output only.

    Extracted from the free-form note rather than given its own input field — a provisional
    decision (미결정_대장 18.2 #10), so expect this to move.
    """

    appearance: str
    outfit: str


class NeedsInput(Base):
    """Contract: `components.schemas.NeedsInput`. Inference ran and could not decide.

    ⚠️ Not for dependency outages. When `brief:fill` never answered, two fields are missing
    rather than one, so that case is `messageMode: degraded` instead (ADR-0005). The screen
    tells the two apart by whether this key is present, so do not reuse it.

    Stored on the session, not recomputed per response: recomputing would reword `reason` on
    every read and call the model again each time.
    """

    field: str = Field(description="브리프 필드 이름")
    reason: str = Field(description="사람에게 보여 줄 문장")


class Brief(Base):
    """Contract: `components.schemas.Brief`. Editable up to `brief_ready`, then locked.

    `outputType` and `panelCount` are deliberately absent. The first lives on the session
    (a copy would need a rule for which side wins after a patch); the second is
    `visibility: hidden`, and a hidden value that ships to the client and gets hidden by the
    screen is not hidden.

    ⚠️ Fields that do not apply to the output type are **absent**, not empty: no
    `aspectRatio` on a comic, no `character` on a single ad. `Session` enforces that pairing
    — `Brief` alone cannot, because it does not know the output type.
    """

    product_image_url: str = Field(
        description="업로드 사진 1장의 참조 URL. 보존 24시간 (세션_보관_정책 2절)"
    )
    product_name: str = Field(min_length=1, max_length=40)
    selling_point: str = Field(
        min_length=1,
        max_length=200,
        description="가드레일의 근거 원문. 여기에 없는 수치와 효능은 생성물에 등장할 수 없습니다",
    )
    note: str = Field(max_length=500, description='선택 항목. 비어 있으면 `null`이 아니라 ""')
    category: str = Field(description="추론값. 가드레일의 근거가 아닙니다")
    target: str = Field(description="추론값. 가드레일의 근거가 아닙니다")
    art_style: str
    character: Omittable[Character] = None
    aspect_ratio: Omittable[str] = None


def check_brief_matches_output_type(output_type: OutputType, brief: Brief) -> None:
    """Reject fields that do not apply to the output type.

    Lives here rather than on `Brief` because `Brief` has no `outputType` — every caller
    that holds both is expected to run this. Raises `ValueError` so pydantic reports it as
    a validation error (422) wherever it is called from a `model_validator`.
    """
    if output_type == "comic" and brief.aspect_ratio is not None:
        raise ValueError("aspectRatio does not apply to comic output; omit the key")
    if output_type == "single_ad" and brief.character is not None:
        raise ValueError("character does not apply to single_ad output; omit the key")
