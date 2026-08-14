"""Session routes: create one, list them, read one.

Contract: packages/contracts/openapi.yaml, the `sessions` tag.

⚠️ Thin, like every router here (apps/backend/AGENTS.md): validate, call `session_flow`,
map the response. What a session *becomes* is decided in `backend_core.session_flow`, and
whether a transition is allowed in `backend_core.state`. If a rule starts being expressed
in this file, it has escaped the place it can be tested without HTTP.

⚠️ **A session that is not yours does not exist.** Every read goes through
`sessions.for_user`, which takes the requester's id as a required argument and answers
`None` for both "no such session" and "someone else's" (INV-9). 403 would confirm the id is
real, which is exactly what an attacker walking the id space is trying to learn.
"""

from __future__ import annotations

import logging
import random
import sqlite3
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, status

from api import deps
from api.errors import invalid_image, not_found
from api.schemas import SessionCreateRequest
from backend_core import images, session_flow, sessions
from backend_core.accounts import Account
from backend_core.ai_client import AiEngineClient, AiEngineUnavailableError
from backend_core.config import Settings
from backend_core.models import BriefFillResponse, Session, SessionSummary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionSummary])
def list_sessions(
    account: Annotated[Account, Depends(deps.current_user)],
    connection: Annotated[sqlite3.Connection, Depends(deps.db)],
) -> list[SessionSummary]:
    """This user's sessions, newest first.

    Recovering this list is the whole job the account does in the first cut
    (세션_보관_정책.md 1.3절) — which makes an empty list a normal answer, not an error.
    """
    return sessions.list_for_user(connection, account.user_id)


@router.post("", response_model=Session, status_code=status.HTTP_201_CREATED)
def create_session(
    body: Annotated[SessionCreateRequest, Form(media_type="multipart/form-data")],
    account: Annotated[Account, Depends(deps.current_user)],
    connection: Annotated[sqlite3.Connection, Depends(deps.db)],
    settings: Annotated[Settings, Depends(deps.settings)],
    engine: Annotated[AiEngineClient, Depends(deps.ai_client)],
) -> Session:
    """Take the photo and the product details, and try to fill the rest in.

    ⚠️ **201 does not mean the brief is complete.** Three outcomes share this status, and
    the client tells them apart by `state` and by whether `needsInput` is present — the
    table is in `session_flow.create`. Two of the three are not errors: missing information
    is a step in the conversation (기획서 9.3), and a dependency outage is a designed
    degradation (ADR-0005).

    The photo rides in this one request rather than a separate upload step. Splitting it
    doubles the round trips and invents "an image belonging to no session", which would need
    its own retention and ownership rules (API_계약.md 8.1절).
    """
    payload = body.product_image.file.read()
    session_id = sessions.new_session_id()
    try:
        image_url = images.store(settings.image_dir, session_id, payload)
    except images.InvalidImageError as exc:
        invalid_image(str(exc))

    session = session_flow.create(
        session_flow.CreateInput(
            session_id=session_id,
            output_type=body.output_type,
            product_image_url=image_url,
            product_name=body.product_name,
            selling_point=body.selling_point,
            # The contract has no nulls: an omitted note is `""`, not absent-and-then-None.
            note=body.note or "",
            art_style=body.art_style or _pick_art_style(settings),
        ),
        _fill_brief(engine, body, payload),
        sessions.now(),
    )
    return sessions.save(connection, account.user_id, session)


@router.get("/{session_id}", response_model=Session)
def get_session(
    session_id: UUID,
    account: Annotated[Account, Depends(deps.current_user)],
    connection: Annotated[sqlite3.Connection, Depends(deps.db)],
) -> Session:
    """One session in full. 404 if it is not yours (INV-9)."""
    session = sessions.for_user(connection, account.user_id, session_id)
    if session is None:
        not_found("세션을 찾을 수 없습니다.")
    return session


def _pick_art_style(settings: Settings) -> str:
    """Fill in a style the user did not choose.

    ⚠️ Returns `""` while the candidate list is empty, and the list is empty because **the
    candidates are not decided** (미결정_대장 A절 3번, 차단). Picking from a hard-coded list
    here would turn a blocked decision into an implemented one, which is the failure the
    미결정 대장 exists to prevent — the value would then be in the code with no record of who
    chose it.

    The random pick is deliberately the mechanism rather than the data, so the decision lands
    as configuration (`ADGEN_ART_STYLES`) and this function stops returning `""` on its own.
    """
    if not settings.art_styles:
        return ""
    # `random` rather than `secrets`: this picks a look, not a secret.
    return random.choice(settings.art_styles).art_style_id  # noqa: S311


def _fill_brief(
    engine: AiEngineClient, body: SessionCreateRequest, payload: bytes
) -> BriefFillResponse | None:
    """Ask the engine to infer `category` and `target`, or answer `None`.

    ⚠️ `None` is the **designed** degradation and the only one in the system (ADR-0005): we
    skip an automation and carry on with what the user typed. Compare the two forbidden
    alternatives — failing the whole request would make an outage in an optional inference
    look like a broken product, and making the two values up would put unsourced text into a
    brief that the guardrail later treats as evidence.

    The exception is swallowed here rather than propagated because the caller has no decision
    left to make: there is exactly one fallback and this is it. It is logged at WARNING so a
    degraded rate that climbs is visible — `messageMode` is a reported metric, and a
    degradation nobody counted is a degradation nobody noticed.
    """
    try:
        return engine.fill_brief(
            product_name=body.product_name,
            selling_point=body.selling_point,
            note=body.note or "",
            image=payload,
            filename=body.product_image.filename or "upload",
        )
    except AiEngineUnavailableError as exc:
        logger.warning("brief:fill unavailable, degrading to user input: %s", exc)
        return None
