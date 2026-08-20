"""Create a session, list them, read one — through HTTP, as a client sees it.

The three questions this file exists to answer:

1. Do the three outcomes of `POST /v1/sessions` come out the way the contract's table says?
2. Does a session survive a restart? (S2's completion condition, and the reason ADR-0010
   ruled out in-memory storage.)
3. Is someone else's session a 404 rather than a 403? (INV-9.)
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from argon2 import PasswordHasher
from conftest import FILLED_CATEGORY, FILLED_TARGET, FakeAiEngine
from conftest import VALID_PNG as PNG
from fastapi.testclient import TestClient

from api import deps
from api.main import app
from backend_core.models import NeedsInput

SECRET = "test-signing-key"  # noqa: S105 - a test fixture, never a deployed key
PASSWORD = "correct-horse-battery-staple"  # noqa: S105 - hashed by the fixture below

# A 1x1 PNG. Real magic bytes, because the format check sniffs the payload rather than
# trusting the filename or the Content-Type — both of which the caller supplies.


@pytest.fixture
def ai() -> FakeAiEngine:
    return FakeAiEngine()


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Two accounts and a database, as a deployment has them.

    Two because INV-9 needs "someone else" to exist — with one account the 404 path in this
    file could not be written at all.
    """
    hasher = PasswordHasher()
    monkeypatch.setenv("ADGEN_DB_PATH", str(tmp_path / "sessions.sqlite"))
    monkeypatch.setenv("ADGEN_IMAGE_DIR", str(tmp_path / "images"))
    monkeypatch.setenv("ADGEN_SESSION_SECRET", SECRET)
    monkeypatch.setenv(
        "ADGEN_ACCOUNTS",
        f'[{{"login_id": "demo1", "password_hash": "{hasher.hash(PASSWORD)}"}},'
        f' {{"login_id": "demo2", "password_hash": "{hasher.hash(PASSWORD)}"}}]',
    )
    deps.settings.cache_clear()
    return tmp_path


@pytest.fixture
def client(env: Path, ai: FakeAiEngine) -> Iterator[TestClient]:
    app.dependency_overrides[deps.ai_client] = lambda: ai
    # ⚠️ `https://` base URL, not decoration: the session cookie carries `Secure`, so an
    # http:// test client accepts it and then never sends it back — every request would be
    # 401 and the failure would look like broken auth rather than a test-setup detail.
    with TestClient(app, base_url="https://testserver") as test_client:
        _login(test_client, "demo1")
        yield test_client
    app.dependency_overrides.clear()


def _login(client: TestClient, login_id: str) -> None:
    response = client.post("/v1/auth/login", json={"loginId": login_id, "password": PASSWORD})
    assert response.status_code == 200, response.text


def _create(client: TestClient, **overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "outputType": "single_ad",
        "productName": "테스트 제품",
        "sellingPoint": "수분감이 오래 갑니다",
        "note": "",
        **overrides,
    }
    response = client.post(
        "/v1/sessions",
        data=fields,
        files={"productImage": ("photo.png", PNG, "image/png")},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# ---- the three outcomes of POST /v1/sessions (contract table) ---------------------------


def test_a_filled_brief_reaches_brief_ready(client: TestClient) -> None:
    body = _create(client)

    assert body["state"] == "brief_ready"
    assert body["messageMode"] == "normal"
    assert body["brief"]["category"] == FILLED_CATEGORY
    assert body["brief"]["target"] == FILLED_TARGET
    assert "needsInput" not in body


def test_needs_input_stays_in_brief_filling_and_is_not_an_error(
    client: TestClient, ai: FakeAiEngine
) -> None:
    """Missing information is a step in the conversation, not a failure (기획서 9.3).

    201 with `needsInput`, and the two inferred fields empty rather than absent — the
    contract has no nulls, so "we could not decide" is `""`.
    """
    ai.needs_input = NeedsInput(field="category", reason="제품군을 판단하지 못했습니다.")

    body = _create(client)

    assert body["state"] == "brief_filling"
    assert body["messageMode"] == "normal"
    assert body["needsInput"]["field"] == "category"
    assert body["brief"]["category"] == ""


def test_an_engine_outage_degrades_instead_of_failing(client: TestClient, ai: FakeAiEngine) -> None:
    """ADR-0005: the one designed degradation in the system.

    ⚠️ Three things at once, and all three matter. Still 201 — an outage in an optional
    inference must not look like a broken product. `degraded` — the mode is a reported
    metric, so a degradation that did not say so would not be counted. And still
    `brief_filling`, **not** `brief_ready`: moving on would let draft generation start with
    an empty category and target, and the brief is the guardrail's evidence.
    """
    ai.available = False

    body = _create(client)

    assert body["state"] == "brief_filling"
    assert body["messageMode"] == "degraded"
    assert body["brief"]["category"] == ""
    assert "needsInput" not in body


def test_the_degraded_and_needs_input_cases_are_told_apart_by_one_key(
    client: TestClient, ai: FakeAiEngine
) -> None:
    """Both sit in `brief_filling`, and the screen has to show different things.

    The contract's discriminator is the presence of `needsInput`, not `messageMode` — this
    pins that the two never collide, because reusing `needsInput` for outages is the obvious
    shortcut and ADR-0005 forbids it.
    """
    ai.available = False
    degraded = _create(client)

    ai.available = True
    ai.needs_input = NeedsInput(field="target", reason="대상을 판단하지 못했습니다.")
    asked = _create(client)

    assert degraded["state"] == asked["state"] == "brief_filling"
    assert "needsInput" not in degraded
    assert "needsInput" in asked


# ---- answering needsInput: the retry (계약 `PATCH .../brief`, 미결정_대장 B-11) ---------


def _patch_brief(client: TestClient, body: dict[str, Any], **patch: Any) -> dict[str, Any]:
    """PATCH the brief the way a client does — **camelCase keys**.

    ⚠️ The conversion is not cosmetic. `Base` sets `populate_by_name=True`, so `art_style`
    would also be accepted and the test would pass while pinning the wrong thing: "the cost
    guard skips `art_style`" instead of "the cost guard skips `artStyle`", which is the name
    the contract and the screen actually use (PR #148 리뷰, 신호정).
    """
    camel = {
        re.sub(r"_(.)", lambda m: m.group(1).upper(), field): value
        for field, value in patch.items()
    }
    response = client.patch(
        f"/v1/sessions/{body['sessionId']}/brief",
        json={"revision": body["revision"], "patch": camel},
    )
    assert response.status_code == 200, response.text
    answer: dict[str, Any] = response.json()
    return answer


def test_answering_needs_input_asks_the_engine_again_and_lets_the_session_out(
    client: TestClient, ai: FakeAiEngine
) -> None:
    """The contract: "`needsInput`이 걸린 세션에서 `note`를 채우면 서버가 추론을 다시 시도합니다".

    ⚠️ **Without the retry this session has no exit.** `category` and `target` are filled by
    inference, nobody else writes them on this path, and `brief_filling -> brief_filling` is
    a legal edge — so the screen would ask for a note for ever however much the user typed.
    That was unreachable while `brief:fill` was a stub and became reachable the day it was
    not (2026-08-20).
    """
    ai.needs_input = NeedsInput(field="note", reason="무슨 제품인지 알기 어렵습니다.")
    created = _create(client)
    assert created["state"] == "brief_filling"

    ai.needs_input = None
    answered = _patch_brief(client, created, note="여름용 수분 크림입니다")

    assert answered["state"] == "brief_ready"
    assert answered["brief"]["category"] == FILLED_CATEGORY
    assert "needsInput" not in answered
    # The retry has to have seen the new note, not the one that already failed.
    assert ai.briefs_requested[-1][2] == "여름용 수분 크림입니다"


def test_the_retry_does_not_overwrite_a_value_the_user_typed_in_the_same_patch(
    client: TestClient, ai: FakeAiEngine
) -> None:
    """기획서 5.4 read from the other side: a correction the person just made stands.

    Filling the blanks is the retry's job; replacing an answer is not. If the user names a
    `category` in the very request that triggers the retry, the model's guess for that field
    is late and wrong to apply.
    """
    ai.needs_input = NeedsInput(field="note", reason="무슨 제품인지 알기 어렵습니다.")
    created = _create(client)

    ai.needs_input = None
    answered = _patch_brief(client, created, note="여름용 수분 크림", category="직접 고른 카테고리")

    assert answered["brief"]["category"] == "직접 고른 카테고리"
    assert answered["briefMeta"]["category"]["filledBy"] == "user"
    # The field the user left alone is the model's, and says so.
    assert answered["brief"]["target"] == FILLED_TARGET
    assert answered["briefMeta"]["target"]["filledBy"] == "inferred"


def test_a_patch_that_cannot_change_the_answer_does_not_pay_for_a_retry(
    client: TestClient, ai: FakeAiEngine
) -> None:
    """`artStyle` is not an input to `brief:fill`, so asking again would buy the same answer.

    The guard is about money, not correctness: every retry is a vendor call, and a screen
    that patches on each edit would multiply them by the number of keystrokes.
    """
    ai.needs_input = NeedsInput(field="note", reason="무슨 제품인지 알기 어렵습니다.")
    created = _create(client)
    calls = len(ai.briefs_requested)

    _patch_brief(client, created, art_style="minimal")

    assert len(ai.briefs_requested) == calls


def test_an_ordinary_patch_on_a_settled_brief_never_calls_the_engine(
    client: TestClient, ai: FakeAiEngine
) -> None:
    """No `needsInput`, no retry. A `brief_ready` session is not waiting on an inference."""
    created = _create(client)
    assert "needsInput" not in created
    calls = len(ai.briefs_requested)

    _patch_brief(client, created, selling_point="가볍게 발립니다")

    assert len(ai.briefs_requested) == calls


def test_a_retry_that_cannot_run_degrades_and_hands_the_user_the_other_way_out(
    client: TestClient, ai: FakeAiEngine
) -> None:
    """The engine went down between the question and the answer.

    ⚠️ `needsInput` is **cleared**, and that is the point rather than a side effect. The
    contract splits the two brief_filling cases on that key: `needsInput` means inference
    ran and could not decide, `degraded` means it could not run. Leaving the key on would
    keep the screen asking for a note that now leads nowhere, while `degraded` is the state
    whose documented exit is "the user fills `category` and `target` themselves".
    """
    ai.needs_input = NeedsInput(field="note", reason="무슨 제품인지 알기 어렵습니다.")
    created = _create(client)

    ai.available = False
    answered = _patch_brief(client, created, note="여름용 수분 크림입니다")

    assert answered["state"] == "brief_filling"
    assert answered["messageMode"] == "degraded"
    assert "needsInput" not in answered

    # And that exit actually works: filling the two by hand reaches brief_ready.
    settled = _patch_brief(client, answered, category="스킨케어", target="20대 여성")
    assert settled["state"] == "brief_ready"


def test_a_retry_that_is_still_undecided_stays_put_rather_than_failing(
    client: TestClient, ai: FakeAiEngine
) -> None:
    """⚠️ **This is the open case, pinned as it is today rather than as the contract wants.**

    The contract promises 422 `INSUFFICIENT_INPUT` and a `failed` session here. It does not
    happen yet, and deliberately: *when* to give up (first failure? third?) is
    미결정_대장 B-11, whose 확정 근거 is 회의록 — the ledger's own rule forbids picking a
    number in code. This test exists so the day that number is decided, the change shows up
    here as a failure instead of passing unnoticed.
    """
    ai.needs_input = NeedsInput(field="note", reason="무슨 제품인지 알기 어렵습니다.")
    created = _create(client)

    ai.needs_input = NeedsInput(field="note", reason="아직도 판단이 서지 않습니다.")
    answered = _patch_brief(client, created, note="음")

    assert answered["state"] == "brief_filling"
    assert answered["messageMode"] == "normal"
    # The reason is refreshed, so the screen shows what is missing *now*.
    assert answered["needsInput"]["reason"] == "아직도 판단이 서지 않습니다."


def test_a_degraded_session_is_still_allowed_to_try_again(
    client: TestClient, ai: FakeAiEngine
) -> None:
    """An outage must not cost the session its retry for ever.

    ⚠️ **This is the trap `wants_refill` fell into** (PR #148 리뷰, 신호정): a failed retry
    clears `needsInput`, so a rule keyed only on `needsInput` turned one bad second into a
    permanent loss of auto-fill — with nothing on screen to say why. The user would keep
    rewriting the note and keep getting blanks.
    """
    ai.needs_input = NeedsInput(field="note", reason="무슨 제품인지 알기 어렵습니다.")
    created = _create(client)

    ai.available = False
    degraded = _patch_brief(client, created, note="여름용 수분 크림")
    assert degraded["messageMode"] == "degraded"

    ai.available = True
    ai.needs_input = None
    recovered = _patch_brief(client, degraded, note="여름용 수분 크림, 무향입니다")

    assert recovered["state"] == "brief_ready"
    assert recovered["messageMode"] == "normal"
    assert recovered["brief"]["category"] == FILLED_CATEGORY


def test_saving_the_same_note_again_does_not_pay_for_the_same_answer(
    client: TestClient, ai: FakeAiEngine
) -> None:
    """The guard compares values, not keys.

    A screen that autosaves, or a person fixing a typo and saving twice, sends `note` every
    time. Billing each one buys the identical answer repeatedly (PR #148 리뷰, 신호정).
    """
    ai.needs_input = NeedsInput(field="note", reason="무슨 제품인지 알기 어렵습니다.")
    created = _create(client)

    ai.needs_input = NeedsInput(field="note", reason="아직도 판단이 서지 않습니다.")
    once = _patch_brief(client, created, note="여름용 수분 크림")
    after_first = len(ai.briefs_requested)

    twice = _patch_brief(client, once, note="여름용 수분 크림")

    assert len(ai.briefs_requested) == after_first
    assert twice["needsInput"]["reason"] == "아직도 판단이 서지 않습니다."


def test_a_brief_with_nothing_left_to_infer_does_not_call_the_engine(
    client: TestClient, ai: FakeAiEngine
) -> None:
    """A settled brief has no blank for the retry to fill, so the call is bought to be thrown away.

    ⚠️ The reachable case is a **degraded session the user finished by hand**: `messageMode`
    stays `degraded` after `replace_brief` moves it to `brief_ready`, so a rule keyed only on
    the mode would keep paying for retries on a brief that is already complete. `_fold_refill`
    fills blanks only, so every one of those answers would be discarded.
    """
    ai.available = False
    degraded = _create(client)
    settled = _patch_brief(client, degraded, category="스킨케어", target="20대 여성")
    assert settled["state"] == "brief_ready"
    assert settled["messageMode"] == "degraded"

    ai.available = True
    calls = len(ai.briefs_requested)
    _patch_brief(client, settled, note="나중에 덧붙인 메모")

    assert len(ai.briefs_requested) == calls


def test_a_photo_deleted_between_finding_it_and_reading_it_degrades(
    client: TestClient, ai: FakeAiEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sweeper runs on a timer **in this process**, so the two calls are a race.

    ⚠️ Finding the file and opening it are separate syscalls, and the window is widest at
    exactly 24 hours — which is when the user is most likely to be answering yesterday's
    `needsInput`. Before the fix this answered a 500 to the very request carrying them to
    the exit (PR #148 리뷰에서 신호정 재현).
    """
    ai.needs_input = NeedsInput(field="note", reason="무슨 제품인지 알기 어렵습니다.")
    created = _create(client)

    def vanished(self: Path) -> bytes:
        raise FileNotFoundError(self)

    monkeypatch.setattr(Path, "read_bytes", vanished)
    answered = _patch_brief(client, created, note="여름용 수분 크림입니다")

    assert answered["messageMode"] == "degraded"
    assert "needsInput" not in answered


def test_a_retry_whose_photo_expired_degrades_rather_than_asking_without_it(
    client: TestClient, ai: FakeAiEngine, env: Path
) -> None:
    """`brief:fill` reads the picture as well as the words, and the picture lives 24 hours.

    Sending the words alone would be a different question with a worse answer, and the
    answer would be recorded as the model's. Degrading is the honest report — the inference
    could not run — and it is the retention policy working, not a fault (세션_보관_정책 2절).
    """
    ai.needs_input = NeedsInput(field="note", reason="무슨 제품인지 알기 어렵습니다.")
    created = _create(client)

    for photo in (env / "images").iterdir():
        photo.unlink()
    calls = len(ai.briefs_requested)

    answered = _patch_brief(client, created, note="여름용 수분 크림입니다")

    assert len(ai.briefs_requested) == calls
    assert answered["messageMode"] == "degraded"
    assert "needsInput" not in answered


# ---- durability (S2's completion condition, ADR-0010) -----------------------------------


def test_a_session_survives_a_restart(client: TestClient, env: Path, ai: FakeAiEngine) -> None:
    """The reason ADR-0010 ruled out in-memory storage, as a test.

    A second `TestClient` is a second application lifespan against the same file — the
    closest a unit test gets to `docker compose down && up`. If sessions lived in a
    process-local dict this is where "확정을 눌렀는데 결과가 없다" would show up.
    """
    session_id = _create(client)["sessionId"]

    with TestClient(app, base_url="https://testserver") as restarted:
        _login(restarted, "demo1")
        response = restarted.get(f"/v1/sessions/{session_id}")

    assert response.status_code == 200
    assert response.json()["sessionId"] == session_id


def test_the_image_is_written_to_disk_and_only_its_url_is_stored(
    client: TestClient, env: Path
) -> None:
    """ADR-0010: bytes on disk, a reference in the row. A photo in a database column would
    carry the whole file into every backup and every read of the session.

    ⚠️ The reference is the **URL**, not the path. Until 2026-08-15 it was the path and the
    contract calls the field `productImageUrl` (미결정_대장 N17), so the value was a contract
    violation that no browser could render."""
    body = _create(client)
    session_id = body["sessionId"]

    assert body["brief"]["productImageUrl"] == f"/v1/sessions/{session_id}/image"
    assert (env / "images" / f"{session_id}.png").read_bytes() == PNG


# ---- N17: 이미지 조회 (API_계약.md 8.4절) ------------------------------------------------


def test_the_stored_url_is_the_one_that_serves_the_photo(client: TestClient) -> None:
    """The point of the whole item: the value on the brief is fetchable as-is. A test that
    built the path itself would still pass if the two ever drifted apart."""
    body = _create(client)

    response = client.get(body["brief"]["productImageUrl"])

    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"


def test_the_photo_is_not_offered_to_a_shared_cache(client: TestClient) -> None:
    """An uploaded photo may be personal data, and a proxy is going in front of this service
    before deployment (API_계약.md 8.3절)."""
    body = _create(client)

    response = client.get(body["brief"]["productImageUrl"])

    assert "private" in response.headers["cache-control"]


def test_inv_9_someone_elses_photo_is_404(client: TestClient) -> None:
    """⚠️ The session route already answers 404 for a stranger, and the image route has to
    answer the same — a serving route that only checked the file would hand out every photo
    to anyone who could guess a `sessionId`."""
    session_id = _create(client)["sessionId"]

    _login(client, "demo2")
    mine = client.get(f"/v1/sessions/{session_id}/image")
    invented = client.get("/v1/sessions/00000000-0000-4000-8000-000000000000/image")

    assert mine.status_code == 404
    assert mine.json() == invented.json()


def test_an_expired_photo_is_404_while_the_session_still_answers(
    client: TestClient, env: Path
) -> None:
    """The retention gap, not an error: the photo keeps 24 hours and the session seven days
    (세션_보관_정책.md 2절), so this state is one the design creates on purpose."""
    session_id = _create(client)["sessionId"]
    (env / "images" / f"{session_id}.png").unlink()

    assert client.get(f"/v1/sessions/{session_id}/image").status_code == 404
    assert client.get(f"/v1/sessions/{session_id}").status_code == 200


def test_the_photo_needs_a_login(client: TestClient) -> None:
    session_id = _create(client)["sessionId"]

    client.post("/v1/auth/logout")

    assert client.get(f"/v1/sessions/{session_id}/image").status_code == 401


# ---- INV-9 -----------------------------------------------------------------------------


def test_inv_9_someone_elses_session_is_404_not_403(client: TestClient, ai: FakeAiEngine) -> None:
    """403 would confirm the id exists, which is what an attacker walking ids wants to know.

    The session is real and the requester is authenticated — the only thing wrong is whose
    it is, and the answer must be identical to the answer for an id that never existed.
    """
    session_id = _create(client)["sessionId"]

    _login(client, "demo2")
    mine = client.get(f"/v1/sessions/{session_id}")
    invented = client.get("/v1/sessions/00000000-0000-4000-8000-000000000000")

    assert mine.status_code == 404
    assert mine.json() == invented.json()


def test_inv_9_the_list_only_shows_your_own(client: TestClient) -> None:
    _create(client)
    _create(client)

    _login(client, "demo2")
    assert client.get("/v1/sessions").json() == []


def test_the_list_is_newest_first_and_carries_no_draft(client: TestClient) -> None:
    """Summaries, not sessions: a list endpoint that shipped every draft would grow without
    bound as work accumulates (contract, `SessionSummary`)."""
    first = _create(client, productName="첫번째")
    second = _create(client, productName="두번째")

    body = client.get("/v1/sessions").json()

    assert [row["sessionId"] for row in body] == [second["sessionId"], first["sessionId"]]
    assert [row["productName"] for row in body] == ["두번째", "첫번째"]
    assert all("draft" not in row for row in body)


# ---- auth and validation ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/v1/sessions"),
        ("get", "/v1/sessions/00000000-0000-4000-8000-000000000000"),
        ("get", "/v1/templates"),
        ("get", "/v1/art-styles"),
    ],
)
def test_every_session_route_requires_a_session(
    env: Path, ai: FakeAiEngine, method: str, path: str
) -> None:
    """Everything except /health and /v1/auth/* is behind the cookie (API_계약.md 6절)."""
    app.dependency_overrides[deps.ai_client] = lambda: ai
    with TestClient(app, base_url="https://testserver") as anonymous:
        response = anonymous.request(method, path)
    app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_a_non_image_upload_is_422_invalid_image(client: TestClient) -> None:
    """Sniffed from the bytes. A `.png` filename and an `image/png` header are both supplied
    by the caller, so trusting either would make the check check nothing."""
    response = client.post(
        "/v1/sessions",
        data={
            "outputType": "single_ad",
            "productName": "테스트 제품",
            "sellingPoint": "수분감이 오래 갑니다",
        },
        files={"productImage": ("photo.png", b"GIF89a not really a png", "image/png")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"


def test_an_oversized_selling_point_is_refused_rather_than_truncated(client: TestClient) -> None:
    """The contract refuses instead of trimming: silently cutting it means the tail of what
    the user wrote disappears from the ad and nobody can explain why."""
    response = client.post(
        "/v1/sessions",
        data={
            "outputType": "single_ad",
            "productName": "테스트 제품",
            "sellingPoint": "가" * 201,
        },
        files={"productImage": ("photo.png", PNG, "image/png")},
    )

    assert response.status_code == 422


def test_the_catalog_art_styles_are_empty_until_the_decision_lands(client: TestClient) -> None:
    """⚠️ Pinned deliberately. 미결정_대장 A절 3번 is 차단, and the contract says this route's
    shape is fixed while its contents are not. A day when this returns hard-coded candidates
    is a day a blocked decision got made in code instead of in a 회의록."""
    assert client.get("/v1/art-styles").json() == []


def test_the_catalog_offers_both_output_types(client: TestClient) -> None:
    body = client.get("/v1/templates").json()
    assert {row["outputType"] for row in body} == {"comic", "single_ad"}
