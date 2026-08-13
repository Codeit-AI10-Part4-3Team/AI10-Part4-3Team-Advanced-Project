"""Contract schemas that cannot live in `backend_core` — the multipart ones.

Every other contract schema is in `backend_core.models`. These are here for one reason:
they describe an **uploaded file**, and the only way to say that in Python is to name
Starlette's `UploadFile`. `backend_core` must stay importable without a web framework so
the eval harness and offline tools can call the domain directly (apps/backend/AGENTS.md),
so a transport-only shape belongs on this side of the line.

⚠️ That makes this the one place a reviewer must check by hand when the contract's
multipart bodies change — `tests/backend_core/models/test_contract_conformance.py` holds its conformance test.
"""

from typing import Annotated

from fastapi import UploadFile
from pydantic import Field

from backend_core.models.common import Base, Omittable, OutputType


class SessionCreateRequest(Base):
    """Contract: `components.schemas.SessionCreateRequest`. `multipart/form-data`.

    ⚠️ Bind it as `Annotated[SessionCreateRequest, Form(media_type="multipart/form-data")]`.
    Leave the media type off and the request still works, but the generated `/openapi.json`
    advertises `application/x-www-form-urlencoded` — the spec lies while the wire stays
    correct, which is the exact failure mode the conformance tests exist to catch.

    The photo rides along in this one request rather than a separate upload step. Splitting
    it doubles the round trips and invents "an image belonging to no session", a state that
    would need its own retention and ownership rules (API_계약.md 8.1절).
    """

    output_type: OutputType
    product_image: UploadFile = Field(
        description=(
            "1장. JPEG / PNG / WebP, 최대 10MB, 짧은 변 512px 이상. GIF 와 HEIC 는 받지 않습니다. "
            "규격 위반은 422 INVALID_IMAGE — 실제 검사는 도메인 계층 소관이며 여기서는 받기만 합니다"
        )
    )
    product_name: str = Field(min_length=1, max_length=40)
    selling_point: str = Field(min_length=1, max_length=200)
    note: Omittable[Annotated[str, Field(max_length=500)]] = None
    art_style: Omittable[str] = Field(
        default=None, description="선택. 미선택 시 후보군에서 무작위로 채웁니다"
    )
