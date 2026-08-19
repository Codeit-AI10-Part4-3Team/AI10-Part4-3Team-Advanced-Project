"""광고 생성 경로의 종단 관통 — 입력 접수부터 결과 이미지까지, HTTP 계약만으로.

⚠️ `test_harness.py` 의 `/v1/ask` 는 **템플릿 질의응답 경로**입니다. 그것이 초록이어도 광고
경로는 한 줄도 지나가지 않습니다. 이 파일이 없으면 "종단 관통 테스트 통과"가 관통을 뜻하지
않는 상태가 되고, 그것이 `AGENTS.md` 가 말하는 "게이트 통과 ≠ 관통 경로 검증"입니다.

관통 경로는 **단일 광고형 하나**입니다 (구현_범위.md 1절). 만화형은 분기만 둔 스텁이므로
여기서 통과를 요구하지 않습니다 — 요구하면 스텁의 현재 동작이 계약으로 굳습니다.
"""

import time

import httpx
import pytest

# 잡이 끝나기를 기다리는 상한. 스텁 렌더는 초 단위지만 실물은 한 장에 54~122초입니다
# (2026-08-14 실측). 상한을 실물 기준으로 두는 이유는, `ADGEN_GENERATION_MODE=model` 로
# 돌리는 날 이 테스트가 "모델이 느려서" 빨간불이 되지 않게 하기 위함입니다.
JOB_DEADLINE_S = 240

# `Retry-After` 가 이상한 값이거나 없을 때의 하한. **기본 간격이 아닙니다** — 간격의 주인은
# 서버이고, 이것은 폴링이 멈추거나 폭주하지 않게 하는 안전선입니다.
FALLBACK_INTERVAL_S = 3


def _create_session(client: httpx.Client, image: bytes, product_name: str) -> dict:
    """사진과 제품 정보를 한 번에 보냅니다 (API_계약.md 8.1절)."""
    response = client.post(
        "/v1/sessions",
        files={"productImage": ("product.png", image, "image/png")},
        data={
            "outputType": "single_ad",
            "productName": product_name,
            "sellingPoint": "원두를 주문 후에 갈아 내려 산미가 살아 있습니다. 500g 한 봉지 기준입니다.",
            "note": "따뜻한 일상 분위기로 부탁합니다.",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.flow
def test_ad_session_threads_from_input_to_image(signed_in: httpx.Client, product_image: bytes):
    """입력 -> 브리프 -> 시안 -> 확정 -> 렌더 -> 결과 이미지. 한 세션이 전 구간을 지납니다."""
    session = _create_session(signed_in, product_image, "관통 확인 커피")
    session_id = session["sessionId"]

    # ⚠️ 201 이 "브리프가 다 채워졌다"는 뜻은 아닙니다. 정상 · 정보 부족 · 열화 셋이 같은
    #    상태 코드를 쓰므로 `state` 로 갈라야 합니다. 여기서 `brief_ready` 를 요구하는 것은
    #    ai-engine 이 살아 있는 스택을 전제하기 때문이고, 그것이 이 테스트의 대조군입니다.
    assert session["state"] == "brief_ready", session
    assert session["messageMode"] == "normal"

    # 사진의 참조는 **앱 상대 경로**입니다. 절대 URL 이 오면 배포에서 종단이 바뀔 때 어긋납니다.
    assert session["brief"]["productImageUrl"] == f"/v1/sessions/{session_id}/image"

    photo = signed_in.get(session["brief"]["productImageUrl"])
    assert photo.status_code == 200, photo.text
    # 올린 형식 그대로 돌려줍니다 — 재인코딩하지 않습니다.
    assert photo.headers["content-type"] == "image/png"

    # ---- 시안. 이 요청이 브리프를 잠급니다 (INV-7) -------------------------------------
    drafted = signed_in.post(f"/v1/sessions/{session_id}/draft")
    assert drafted.status_code == 200, drafted.text
    body = drafted.json()
    assert body["state"] == "draft_ready", body
    draft = body["draft"]
    # 시안은 **텍스트만** 담습니다. 이미지 경로가 여기 있으면 "확정 전에는 그림을 만들지
    # 않는다"가 깨진 것입니다.
    assert draft["adPlan"] and draft["copy"] and draft["visualPlan"], draft
    assert "panels" not in draft

    # ---- 확정. 동기와 비동기가 갈리는 유일한 지점 --------------------------------------
    accepted = signed_in.post(f"/v1/sessions/{session_id}/finalize")
    assert accepted.status_code == 202, accepted.text
    job_id = accepted.json()["jobId"]
    assert accepted.json()["statusUrl"] == f"/v1/jobs/{job_id}"

    # ---- 폴링. 간격은 서버가 정합니다 --------------------------------------------------
    deadline = time.monotonic() + JOB_DEADLINE_S
    while True:
        polled = signed_in.get(f"/v1/jobs/{job_id}")
        # ⚠️ **렌더가 실패해도 200 입니다.** 조회는 성공했고 잡이 실패한 것이므로, 여기서
        #    4xx/5xx 를 허용하면 "서버에 못 닿았다"와 "그림을 못 만들었다"가 섞입니다.
        assert polled.status_code == 200, polled.text
        job = polled.json()
        if job["status"] in {"done", "failed"}:
            break

        # 계약: `Retry-After` 는 `queued` · `running` 일 때만 실립니다. 안 실으면 클라이언트가
        # 간격을 하드코딩하게 되고, 큐가 밀릴 때 서버가 늦출 방법이 없어집니다.
        retry_after = polled.headers.get("Retry-After")
        assert retry_after is not None, f"{job['status']} 인데 Retry-After 가 없습니다"
        assert time.monotonic() < deadline, f"{JOB_DEADLINE_S}초 안에 끝나지 않았습니다: {job}"
        time.sleep(max(int(retry_after), 1) if retry_after.isdigit() else FALLBACK_INTERVAL_S)

    assert job["status"] == "done", job.get("error", job)
    # 끝난 잡에는 다음 조회가 없습니다. 여기에 `Retry-After` 가 실리면 클라이언트가 영원히
    # 다시 물어보게 됩니다.
    assert "Retry-After" not in polled.headers

    # ---- 결과 내려받기 ------------------------------------------------------------------
    result = job["result"]
    assert result["imageUrl"] == f"/v1/jobs/{job_id}/image"
    assert result["width"] > 0 and result["height"] > 0
    assert result["expiresAt"]  # 만료를 404 가 아니라 이 값으로 미리 압니다

    image = signed_in.get(result["imageUrl"])
    assert image.status_code == 200, image.text
    # 무손실 WebP. 한국어 글자가 그려지는 경로라 손실 압축을 쓰지 않습니다.
    assert image.headers["content-type"] == "image/webp"
    assert len(image.content) > 0

    # ---- 세션은 `completed`. 잡의 `done` 과 다른 층입니다 (용어_사전.md 1.4절) -----------
    final = signed_in.get(f"/v1/sessions/{session_id}")
    assert final.status_code == 200, final.text
    assert final.json()["state"] == "completed"
    assert final.json()["jobId"] == job_id


@pytest.mark.failure
def test_another_users_session_is_404_not_403(
    signed_in: httpx.Client, other_signed_in: httpx.Client, product_image: bytes
):
    """남의 세션은 403이 아니라 **404** 입니다 (INV-9).

    403 은 "있지만 당신 것이 아니다"를 알려 주므로 `sessionId` 를 훑으며 존재 여부를 캐낼 수
    있습니다. **계정이 둘이어야 이 경로를 지납니다** — 고정 계정 둘이 최소값인 이유입니다.
    """
    session_id = _create_session(signed_in, product_image, "남의 세션")["sessionId"]

    # 주인은 볼 수 있습니다. 대조군이 없으면 "404 가 나왔다"가 소유권 판정 때문인지
    # 세션이 애초에 없어서인지 구분되지 않습니다.
    assert signed_in.get(f"/v1/sessions/{session_id}").status_code == 200

    stranger = other_signed_in.get(f"/v1/sessions/{session_id}")
    assert stranger.status_code == 404, stranger.text
    assert stranger.json()["code"] == "NOT_FOUND"

    # 사진도 같은 규칙입니다. 소유권 검사가 파일 접근보다 먼저 오지 않으면 응답 시간이
    # 존재 여부를 알려 주는 신탁이 됩니다.
    assert other_signed_in.get(f"/v1/sessions/{session_id}/image").status_code == 404


@pytest.mark.failure
def test_ad_paths_require_a_session_cookie(client: httpx.Client):
    """보호 범위는 `/health` 와 `/v1/auth/*` 를 뺀 **모든 `/v1` 경로**입니다 (API_계약 6절).

    프론트가 로그인을 가장 먼저 붙인 이유가 이것이고, 여기가 뚫리면 그 순서가 무의미해집니다.
    """
    for path in ("/v1/sessions", "/v1/me", "/v1/art-styles"):
        response = client.get(path)
        assert response.status_code == 401, f"{path}: {response.status_code} {response.text}"
        # 클라이언트는 `code` 로 분기합니다. FastAPI 기본 `{"detail": ...}` 이 새어 나오면
        # 화면이 그 응답을 오류로 해석하지 못합니다.
        assert set(response.json()) == {"code", "message"}
        assert response.json()["code"] == "UNAUTHORIZED"
