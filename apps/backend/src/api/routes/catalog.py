"""Catalog routes: what the user picks from before a session exists.

Contract: packages/contracts/openapi.yaml, the `catalog` tag. Both are behind the session
cookie — everything except `/health` and `/v1/auth/*` is (API_계약.md 6절).
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from api import deps
from backend_core.config import Settings
from backend_core.models import ArtStyle, Template

# `current_user` sits on the router, not on each handler: the catalog is the same for every
# user, so no handler needs the account — but both routes still document a 401, and a
# router-level dependency is the form that cannot be forgotten on the next route added here.
router = APIRouter(prefix="/v1", tags=["catalog"], dependencies=[Depends(deps.current_user)])

TEMPLATES = [
    Template(output_type="comic", name="만화형", example_image_url=""),
    Template(output_type="single_ad", name="단일 광고형", example_image_url=""),
]
"""The two output types, which are decided (용어_사전.md 1.2절 and the contract's enum).

⚠️ `exampleImageUrl` is empty because **the example images do not exist yet**, and an empty
string is the contract's way of saying "present but empty" (no `null` anywhere). Filling it
with a placeholder that resolves to nothing would look like a broken asset rather than a
missing one, and nobody would know which.

The list is a constant rather than configuration because, unlike the art styles, the output
types are not an open question: adding a third one is a contract change to `OutputType`, and
this list is then the smallest of the edits it takes.
"""


@router.get("/templates", response_model=list[Template])
def list_templates() -> list[Template]:
    """The output types. The screen calls them "템플릿"; the domain does not — `template`
    collides with prompt templates, so it is not an identifier here (용어_사전.md 1.2절)."""
    return TEMPLATES


@router.get("/art-styles", response_model=list[ArtStyle])
def list_art_styles(settings: Annotated[Settings, Depends(deps.settings)]) -> list[ArtStyle]:
    """The art-style candidates.

    ⚠️ **Empty until the candidates are decided** (미결정_대장 A절 3번, 차단). The contract
    already says so: "이 경로의 응답 모양은 확정이고, 그 안에 실릴 값이 아직 없습니다."

    Read from configuration rather than from a list in this file, so the decision can land
    as data and so nothing in this repo ever reads as though it had already been made. When
    it does land, each entry needs a reference image generated with the same prompt fragment
    the real run uses — a picker whose sample does not match the result lies (2026-08-11 회의).
    """
    return settings.art_styles
