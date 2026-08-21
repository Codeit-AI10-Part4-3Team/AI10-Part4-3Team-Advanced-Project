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
import secrets
import sqlite3
from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Path, status
from fastapi.responses import FileResponse

from api import deps
from api.errors import (
    ApiError,
    content_policy_rejected,
    generation_timeout,
    invalid_image,
    invalid_request,
    not_found,
    state_conflict,
    upstream_unavailable,
)
from api.schemas import SessionCreateRequest
from backend_core import images, jobs, observability, session_flow, sessions
from backend_core.accounts import Account
from backend_core.ai_client import (
    AiEngineClient,
    AiEngineUnavailableError,
    GenerationTimeoutError,
)
from backend_core.config import Settings
from backend_core.models import (
    Brief,
    BriefFillResponse,
    BriefPatchRequest,
    DraftGenerateRequest,
    DraftPatchEngineRequest,
    DraftPatchRequest,
    FinalizeAccepted,
    Session,
    SessionSummary,
    check_patch_matches_output_type,
)
from backend_core.state import StateConflictError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])

SessionId = Annotated[UUID, Path(alias="sessionId")]
"""The path parameter, named as the contract names it.

⚠️ The route template says `sessionId` and this alias repeats it, because FastAPI would
otherwise publish the Python name (`session_id`). The URL a client sends is identical either
way — a path parameter's *name* never travels — so getting this wrong changes nothing on the
wire and everything in the **published** `/openapi.json`, which then disagrees with
`openapi.yaml` (`components.parameters.SessionId`). A generated client takes its parameter
names from the spec, not from the traffic.

Same failure mode as leaving `media_type` off a multipart body (api/schemas.py): the spec
lies while the traffic stays correct, so nothing fails until someone generates from it.
"""


@router.get("")
def list_sessions(
    account: Annotated[Account, Depends(deps.current_user)],
    connection: Annotated[sqlite3.Connection, Depends(deps.db)],
) -> list[SessionSummary]:
    """This user's sessions, newest first.

    Recovering this list is the whole job the account does in the first cut
    (세션_보관_정책.md 1.3절) — which makes an empty list a normal answer, not an error.
    """
    return sessions.list_for_user(connection, account.user_id)


@router.post("", status_code=status.HTTP_201_CREATED)
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
    return sessions.create(connection, account.user_id, session)


@router.get("/{sessionId}")
def get_session(
    session_id: SessionId,
    account: Annotated[Account, Depends(deps.current_user)],
    connection: Annotated[sqlite3.Connection, Depends(deps.db)],
) -> Session:
    """One session in full. 404 if it is not yours (INV-9)."""
    session, _ = _owned(connection, account, session_id)
    return session


@router.get(
    "/{sessionId}/image",
    response_class=FileResponse,
    responses={200: {"content": {mime: {} for mime in images.MEDIA_TYPE.values()}}},
)
def get_session_image(
    session_id: SessionId,
    account: Annotated[Account, Depends(deps.current_user)],
    connection: Annotated[sqlite3.Connection, Depends(deps.db)],
    settings: Annotated[Settings, Depends(deps.settings)],
) -> FileResponse:
    """The uploaded photo, as bytes. This is what `Brief.productImageUrl` points at.

    ⚠️ **Ownership first, file second.** `_owned` runs before the disk is touched, so a
    stranger gets the same 404 whether the session exists or not (INV-9) — reading the
    directory first would answer faster for sessions that exist and turn the timing into the
    existence oracle that the 404 is there to prevent.

    A missing file is also a 404, and that is the retention gap rather than an error: the
    photo lives 24 hours and the session seven days (세션_보관_정책.md 2절). The screen is
    not meant to discover this here — `productImageUrl` is emptied when the cleanup batch
    removes the file, so `GET /v1/sessions/{id}` already says so before any `<img>` is drawn
    (API_계약.md 8.4절). No new error code, because an `<img>` never reads the body.
    """
    _owned(connection, account, session_id)

    path = images.find(settings.image_dir, session_id)
    if path is None:
        not_found("이미지를 찾을 수 없습니다.")

    return FileResponse(
        path,
        media_type=images.MEDIA_TYPE[path.suffix],
        headers={"Cache-Control": images.CACHE_CONTROL},
    )


@router.post("/{sessionId}/draft")
def generate_draft(
    session_id: SessionId,
    account: Annotated[Account, Depends(deps.current_user)],
    connection: Annotated[sqlite3.Connection, Depends(deps.db)],
    engine: Annotated[AiEngineClient, Depends(deps.ai_client)],
) -> Session:
    """Write the draft. **This request is what locks the brief** (INV-7).

    Synchronous, unlike the render: this is text, and a polling path is not worth building
    for something that finishes inside a minute (API_계약.md 2절).

    ⚠️ Four ways this ends, and three of them put the session back in `brief_ready` with the
    brief unlocked (ADR-0012). The lock exists to keep a draft's evidence from moving
    underneath it — with no draft there is no evidence to protect, and a session whose
    generation failed would otherwise be stuck: brief locked, nothing to show, no way to
    retry. The failure paths are as much of the design as the success one.
    """
    session, was = _owned(connection, account, session_id)
    session = _guard(lambda: session_flow.start_generating(session, sessions.now()))
    _store(connection, account, session, was)

    # ⚠️ The write above is what claims the session. Two simultaneous requests both read
    # `brief_ready`, both pass the guard, and exactly one of them gets to write
    # `draft_generating` — the loser gets a 409 without ever calling the engine, which is
    # what stops one session from costing two generations.
    #
    # Everything after this point is based on the session as `draft_generating`, so the
    # precondition moves with it.
    was = sessions.Precondition(state=session.state, revision=session.revision)

    # ⚠️ Four outcomes, recorded separately. `refused` is the guardrail working (INV-6) and
    # `timeout` is the engine giving up before we do - collapsing either into "failed" would
    # hide the two numbers most worth watching. Each branch records before it raises, because
    # the helpers below (`generation_timeout` and friends) do not return
    # (backend_core.observability).
    with observability.measured() as elapsed_ms:
        try:
            result = engine.generate_draft(
                DraftGenerateRequest(output_type=session.output_type, brief=session.brief)
            )
        except GenerationTimeoutError:
            observability.record(logger, "draft:generate", "timeout", elapsed_ms())
            _unlock(connection, account, session, was)
            generation_timeout()
        except AiEngineUnavailableError as exc:
            # ⚠️ No fallback here, by decision. `brief:fill` degrades because skipping an
            # inference still leaves the user's own words; a draft has nothing to fall back
            # to, and "something reasonable" would be invented ad copy (ADR-0005).
            observability.record(logger, "draft:generate", "unavailable", elapsed_ms())
            _unlock(connection, account, session, was)
            upstream_unavailable(str(exc))

        if result.draft is None:
            # A refusal is a successful call: the engine could have written something and
            # declined to invent it. Not something to retry around — the guardrail refusing
            # is the design working (INV-6).
            observability.record(logger, "draft:generate", "refused", elapsed_ms())
            _unlock(connection, account, session, was)
            content_policy_rejected(
                "입력한 제품 정보만으로는 광고 문구의 근거가 부족합니다. "
                f"소구점을 구체적으로 적어 주세요. (사유: {result.refusal_reason})"
            )

        observability.record(logger, "draft:generate", "ok", elapsed_ms())

    return _store(
        connection, account, session_flow.apply_draft(session, result, sessions.now()), was
    )


@router.patch("/{sessionId}/brief")
def patch_brief(
    session_id: SessionId,
    body: BriefPatchRequest,
    account: Annotated[Account, Depends(deps.current_user)],
    connection: Annotated[sqlite3.Connection, Depends(deps.db)],
    settings: Annotated[Settings, Depends(deps.settings)],
    engine: Annotated[AiEngineClient, Depends(deps.ai_client)],
) -> Session:
    """Change part of the brief, and ask the engine again if this answers `needsInput`.

    ⚠️ Only the named fields travel. The client does not send the whole document back —
    that would make the *client* the keeper of the original, and a bug in a screen would
    overwrite a brief nobody asked to change.

    409 once a draft exists (INV-7): the brief is a draft's evidence, and evidence that
    moves after the fact leaves nothing to say what the draft was based on.

    ⚠️ **This is the only patch route that can call the engine, and it is the contract that
    says so**: "`needsInput`이 걸린 세션에서 `note`를 채우면 서버가 추론을 다시 시도합니다".
    Without the retry a `needsInput` session has no exit at all — `category` and `target`
    stay empty however much the user writes, `brief_filling -> brief_filling` is a legal
    edge, and the screen asks the same question for ever. That was invisible while
    `brief:fill` was a stub and became reachable the day it was not (2026-08-20).

    ⚠️ The merge runs **before** the retry so the engine sees the note the user just typed.
    Retrying on the old brief would ask the same question again and get the same answer.
    """
    session, was = _owned(connection, account, session_id)
    _require_revision(session, body.revision)

    refill = None
    if session_flow.wants_refill(session, body.patch):
        merged, _ = _guard(lambda: session_flow.merge_brief_patch(session, body.patch))
        refill = _refill_brief(engine, settings, session, merged)

    session = _guard(
        lambda: session_flow.apply_brief_patch(session, body.patch, sessions.now(), refill)
    )
    return _store(connection, account, session, was)


@router.patch("/{sessionId}/draft")
def patch_draft(
    session_id: SessionId,
    body: DraftPatchRequest,
    account: Annotated[Account, Depends(deps.current_user)],
    connection: Annotated[sqlite3.Connection, Depends(deps.db)],
    engine: Annotated[AiEngineClient, Depends(deps.ai_client)],
) -> Session:
    """Change part of the draft.

    ⚠️ Unlike generation, **a failure here changes nothing**: the session stays
    `draft_ready` and the existing draft is still there. There is something to fall back to,
    which is exactly what the generation path lacks — so this one does not unlock anything
    and does not move the state.

    `adPlan` and `role` cannot be named (INV-8, INV-5). They have no field on `DraftPatch`,
    so naming one is an unknown field and a 422 — enforced by the schema's shape rather than
    by a check that a later edit could forget.

    ⚠️ **The output-type pairing is checked here, before the engine is called**, and the
    "before" is the point. The engine answers a mismatched patch with a 422, but
    `ai_client` maps every HTTP failure from the engine to `AiEngineUnavailableError` — so
    letting it travel would tell the user `503 UPSTREAM_UNAVAILABLE` about a request that
    was simply wrong, which is the same misdirection `patch_draft`'s docstring records.
    """
    session, was = _owned(connection, account, session_id)
    _require_revision(session, body.revision)
    if session.draft is None or session.state != "draft_ready":
        state_conflict(f"시안이 아직 없습니다. 세션이 {session.state!r} 상태입니다.")
    try:
        check_patch_matches_output_type(session.output_type, body.patch)
    except ValueError as exc:
        # Same mapping `_guard` applies to the brief patch: the domain check raises a plain
        # `ValueError` and the contract's answer is 422 `INVALID_REQUEST`.
        invalid_request(str(exc))

    try:
        result = engine.patch_draft(
            DraftPatchEngineRequest(
                output_type=session.output_type,
                brief=session.brief,
                draft=session.draft,
                patch=body.patch,
            )
        )
    except GenerationTimeoutError:
        generation_timeout()
    except AiEngineUnavailableError as exc:
        upstream_unavailable(str(exc))

    if result.draft is None:
        content_policy_rejected(f"교체한 내용의 근거가 부족합니다. (사유: {result.refusal_reason})")

    return _store(
        connection, account, session_flow.replace_draft(session, result.draft, sessions.now()), was
    )


@router.post(
    "/{sessionId}/finalize",
    status_code=status.HTTP_202_ACCEPTED,
)
def finalize(
    session_id: SessionId,
    account: Annotated[Account, Depends(deps.current_user)],
    connection: Annotated[sqlite3.Connection, Depends(deps.db)],
) -> FinalizeAccepted:
    """Lock the draft and accept the render as a job.

    **The one place synchronous turns asynchronous.** Everything before this waits for an
    answer; an image takes minutes, so holding the request would hit a timeout before the
    picture existed (API_계약.md 2.1절).

    409 on a second call, and that is the cost defence rather than a nicety: one render per
    session (INV-3), enforced by the state machine having no way back to `finalized`.
    """
    session, was = _owned(connection, account, session_id)
    job_id = jobs.new_job_id()
    at = sessions.now()

    session = _guard(lambda: session_flow.finalize(session, job_id, at))

    # ⚠️ Session first, job second, and the order is the whole defence. The conditional write
    # is what decides which of two simultaneous finalizes wins (INV-3); queueing before it
    # would let the loser enqueue a render and only then find out it had lost — two GPU
    # passes for one session, which is exactly what INV-3 exists to prevent.
    _store(connection, account, session, was)
    jobs.enqueue(connection, account.user_id, str(session_id), job_id, at.isoformat())

    return FinalizeAccepted(job_id=job_id, status_url=f"/v1/jobs/{job_id}")


def _require_revision(session: Session, sent: int) -> None:
    """Turn the domain's optimistic-lock refusal into the contract's 409."""
    try:
        session_flow.require_revision(session, sent)
    except session_flow.RevisionConflictError as exc:
        raise ApiError(
            409,
            "REVISION_CONFLICT",
            f"세션이 이미 revision {exc.expected} 입니다. 보낸 값은 {exc.sent} 입니다. "
            "최신 세션을 다시 읽고 시도하세요.",
        ) from exc


def _unlock(
    connection: sqlite3.Connection,
    account: Account,
    session: Session,
    was: sessions.Precondition,
) -> None:
    """Put a failed generation back where it can be retried (ADR-0012).

    Written to storage before the error response goes out, not after: the response is what
    tells the user to try again, and it must not arrive before the state that makes trying
    again possible.

    ⚠️ The precondition here is the one from **`draft_generating`**, not from the original
    read — this route already wrote once, on the way in. Losing the race at this point means
    someone else moved the session while the engine was working, and their result is the one
    that stands; we are unwinding a request that no longer owns the session.
    """
    try:
        sessions.save(
            connection,
            account.user_id,
            session_flow.fail_draft(session, sessions.now()),
            was,
        )
    except sessions.ConcurrentUpdateError:
        logger.warning("session %s moved while generating; leaving it alone", session.session_id)


def _owned(
    connection: sqlite3.Connection, account: Account, session_id: UUID
) -> tuple[Session, sessions.Precondition]:
    """The session and the version we read it at, or a 404 (INV-9).

    The two travel together so a route cannot write without saying what it read — see
    `sessions.save`.
    """
    found = sessions.for_user(connection, account.user_id, session_id)
    if found is None:
        not_found("세션을 찾을 수 없습니다.")
    return found


def _store(
    connection: sqlite3.Connection,
    account: Account,
    session: Session,
    was: sessions.Precondition,
) -> Session:
    """Write the session back, turning a lost race into the contract's 409.

    ⚠️ A concurrent loser gets `STATE_CONFLICT` and **not** a 500, because from the client's
    side it is the same situation as arriving too late: the session is no longer where this
    request needed it to be. The 202-versus-409 split on two simultaneous finalizes is INV-3
    holding (2026-08-14 실측 — before the conditional write both won and two renders queued).
    """
    try:
        return sessions.save(connection, account.user_id, session, was)
    except sessions.ConcurrentUpdateError:
        state_conflict("세션이 방금 다른 요청으로 바뀌었습니다. 최신 상태를 다시 읽고 시도하세요.")


def _guard[T](operation: Callable[[], T]) -> T:
    """Run a domain call, turning a refusal into the contract's 409 or 422.

    The domain raises `StateConflictError` without knowing about HTTP; this is the one place
    that mapping happens, so a new route cannot answer a conflict with the wrong status.

    ⚠️ Generic because the brief patch now runs the **merge** through here too, before the
    session itself is rebuilt: `merge_brief_patch` raises the same `ValueError` the pairing
    check has always raised, and it has to reach the client as the same 422 whether the
    caller wanted a `Session` back or a merged `Brief`.
    """
    try:
        return operation()
    except StateConflictError as exc:
        state_conflict(
            f"지금은 할 수 없는 요청입니다. 세션이 {exc.current!r} 상태입니다 "
            f"({exc.target!r} 로 넘어갈 수 없습니다)."
        )
    except ValueError as exc:
        # ⚠️ The output-type pairing checks raise a plain `ValueError`
        # (`check_brief_matches_output_type`), and without this it escaped as a **500**:
        # `PATCH .../brief` with `aspectRatio` on a comic, or `character` on a single ad,
        # is a request a client can make while following the contract, because `BriefPatch`
        # carries both fields and cannot know the output type (2026-08-14 실측).
        #
        # The contract's answer is 422 `INVALID_REQUEST`, and the domain message already
        # says which field does not belong.
        invalid_request(str(exc))


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
    # `secrets` rather than `random`, even though nothing here needs to be unpredictable.
    # The two cost the same at one call per session, so there is no trade to make — and a
    # PRNG in request-handling code is a finding every scanner raises (SonarQube S2245),
    # which would mean carrying a suppression forever to keep the weaker one.
    return secrets.choice(settings.art_styles).art_style_id


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
    # ⚠️ `degraded` is recorded as an **outcome, not a failure**. It is the number the
    # report asks for by name (05 일정 08-26), and folding it into a failure rate would both
    # overstate failures and erase the metric (backend_core.observability).
    with observability.measured() as elapsed_ms:
        try:
            filled = engine.fill_brief(
                product_name=body.product_name,
                selling_point=body.selling_point,
                note=body.note or "",
                image=payload,
                filename=body.product_image.filename or "upload",
            )
        except AiEngineUnavailableError as exc:
            logger.warning("brief:fill unavailable, degrading to user input: %s", exc)
            observability.record(logger, "brief:fill", "degraded", elapsed_ms())
            return None

        observability.record(
            logger,
            "brief:fill",
            "needs_input" if filled.needs_input else "filled",
            elapsed_ms(),
        )
        return filled


def _refill_brief(
    engine: AiEngineClient,
    settings: Settings,
    session: Session,
    merged: Brief,
) -> session_flow.RefillOutcome:
    """Ask the engine again, now that the user has answered. Never raises.

    ⚠️ **The photo is read back off disk**, because a brief patch does not carry one. The
    upload happens once, at session creation (API_계약.md 8.1절), and `brief:fill` reads the
    picture as well as the words — sending only the words would be a different question with
    a worse answer.

    A missing photo is not an error here. It is the 24-hour retention doing its job
    (세션_보관_정책.md 2절), and the honest report is the same as an outage: the inference
    could not run. The session degrades, which is precisely the state whose documented exit
    is "the user fills `category` and `target` themselves" — so the person is left with a
    way forward rather than a question about a note.

    ⚠️ **Which is why the read is inside the `try`, and `OSError` lands in the same branch
    as an outage.** Finding the file and opening it are two calls, and the retention sweeper
    runs on a timer in this very process (api/sweeper.py) — so a photo that existed at
    `images.find` can be gone by `read_bytes`, and the window is widest at exactly 24 hours,
    which is when the user is most likely to be answering a `needsInput` from yesterday.
    Letting that escape would answer a 500 to the one request that was carrying the user to
    the exit (PR #148 리뷰에서 신호정 재현). *When* we noticed the file was missing means
    nothing to them.
    """
    photo = images.find(settings.image_dir, session.session_id)
    if photo is None:
        logger.warning(
            "brief:fill retry skipped, photo is gone (session=%s): degrading",
            session.session_id,
        )
        return session_flow.RefillOutcome(filled=None)
    try:
        return session_flow.RefillOutcome(
            filled=engine.fill_brief(
                product_name=merged.product_name,
                selling_point=merged.selling_point,
                note=merged.note,
                image=photo.read_bytes(),
                filename=photo.name,
            )
        )
    except (AiEngineUnavailableError, OSError) as exc:
        logger.warning("brief:fill retry unavailable, degrading to user input: %s", exc)
        return session_flow.RefillOutcome(filled=None)
