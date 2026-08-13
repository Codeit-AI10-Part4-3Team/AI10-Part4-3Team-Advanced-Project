"""Contract schemas that cannot live in `ai_engine.models` — the multipart ones.

Every other contract schema is in `ai_engine.models`. This one is here for a single reason:
it describes an **uploaded file**, and saying that in Python means naming Starlette's
`UploadFile`. `ai_engine.models` is imported by `guardrail` and reached directly by the eval
harness, which must run without a web framework (apps/ai-engine/AGENTS.md), so a
transport-only shape belongs beside `service.py` instead.

⚠️ That makes this the one place a reviewer must check by hand when the contract's multipart
body changes — `tests/models/test_contract_conformance.py` holds its conformance test.
"""

from typing import Annotated

from fastapi import UploadFile
from pydantic import Field

from ai_engine.models.common import Base, Omittable


class BriefFillRequest(Base):
    """Contract: `components.schemas.BriefFillRequest`. `multipart/form-data`.

    ⚠️ Bind it as `Annotated[BriefFillRequest, Form(media_type="multipart/form-data")]`.
    Leave the media type off and the request still works, but the generated `/openapi.json`
    advertises `application/x-www-form-urlencoded` — the spec lies while the wire stays
    correct.

    The image arrives as multipart rather than base64 because base64 inflates the body by a
    third, and as bytes rather than a path because the only permitted coupling between the
    two apps is the HTTP contract (AGENTS.md 아키텍처 경계).
    """

    product_image: UploadFile
    product_name: str = Field(min_length=1, max_length=40)
    selling_point: str = Field(min_length=1, max_length=200)
    note: Omittable[Annotated[str, Field(max_length=500)]] = None
