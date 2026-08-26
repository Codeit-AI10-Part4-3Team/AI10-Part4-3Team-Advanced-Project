"""브라우저에서의 관통 — 스켈레톤 전체 DoD 문장 그대로.

구현_범위.md 1절의 완료 조건은 "**브라우저에서** 입력부터 파일 다운로드까지 한 번에"입니다.
HTTP 로만 확인하면 그 문장의 절반(화면, 라우팅, 폴링, 다운로드)이 검증되지 않은 채 남습니다 —
`test_ad_flow.py` 가 지나는 경로를 사람이 실제로 지날 수 있는지는 다른 질문입니다.

⚠️ 여기서 검사하는 것은 **화면이 계약을 제대로 밟는가**이지 화면의 생김새가 아닙니다.
레이아웃과 문구를 자물쇠로 걸면 디자인을 고칠 때마다 관통 테스트가 빨간불이 되고, 그러면
팀이 이 파일을 먼저 끕니다. 그래서 선택자는 접근성 이름(역할 + 이름)만 씁니다.
"""

import pytest
from playwright.sync_api import Page, expect

# 확정 이후 결과가 나타나기까지. 스텁은 초 단위, 실물은 한 장에 54~122초입니다
# (2026-08-14 실측) — `test_ad_flow.py` 의 상한과 같은 이유로 실물 기준입니다.
RESULT_TIMEOUT_MS = 240_000

# 시안은 동기 호출이고 계약 상한이 60초입니다 (API_계약.md 2절).
DRAFT_TIMEOUT_MS = 90_000

PRODUCT_NAME = "브라우저 관통 커피"


@pytest.mark.flow
def test_browser_walks_from_input_to_download(
    page: Page, web_url: str, credentials: tuple[str, str], product_image: bytes
):
    login_id, password = credentials

    # ---- 미인증이면 로그인 화면입니다 ---------------------------------------------------
    # 접근 제어의 본체는 서버(401 · 404)이고 이것은 편의이지만, 편의가 죽으면 사용자는
    # 401 만 받는 화면에 갇힙니다.
    page.goto(web_url)
    expect(page).to_have_url(f"{web_url}/login")

    page.get_by_label("아이디").fill(login_id)
    page.get_by_label("비밀번호").fill(password)
    page.get_by_role("button", name="로그인").click()
    expect(page).to_have_url(f"{web_url}/")

    # ---- 입력. 사진과 제품 정보가 한 화면에서 나갑니다 ----------------------------------
    page.set_input_files(
        "input[type=file]",
        files=[{"name": "product.png", "mimeType": "image/png", "buffer": product_image}],
    )
    # ⚠️ **필수 표기를 이름에 넣지 않습니다.** `제품명 (필수)` 로 적으면 그 표기를 손볼
    #    때마다 여기가 함께 깨집니다. 접근성 이름은 부분 일치라 이 값으로도 각각 하나에만
    #    붙는 것을 확인했습니다 (PR #266 리뷰, 신호정).
    page.get_by_label("제품명").fill(PRODUCT_NAME)
    page.get_by_label("제품 장점").fill(
        "원두를 주문 후에 갈아 내려 산미가 살아 있습니다. 500g 한 봉지 기준입니다."
    )
    page.get_by_role("button", name="광고 만들기 시작").click()

    # 세션이 생긴 순간부터 진행 상태의 주인은 URL 입니다. 화면이 따로 보관하면 새로고침에서
    # 어긋납니다 — 아래에서 실제로 새로고침해 확인합니다.
    page.wait_for_url(f"{web_url}/sessions/**", timeout=DRAFT_TIMEOUT_MS)
    expect(page.get_by_role("heading", name=PRODUCT_NAME)).to_be_visible()
    # 업로드한 사진이 되돌아옵니다 (`productImageUrl` -> `<img src>`).
    expect(page.get_by_role("img", name="업로드한 제품 사진")).to_be_visible()

    # ---- 시안 ---------------------------------------------------------------------------
    page.get_by_role("button", name="시안 만들기").click()
    expect(page.get_by_role("heading", name="광고 기획안")).to_be_visible(timeout=DRAFT_TIMEOUT_MS)

    # ---- 확정하면 폴링이 시작되고, 끝나면 화면이 스스로 바뀝니다 -------------------------
    page.get_by_role("button", name="확정하고 이미지 만들기").click()
    result_image = page.get_by_role("img", name=f"{PRODUCT_NAME} 광고 결과 이미지")
    expect(result_image).to_be_visible(timeout=RESULT_TIMEOUT_MS)

    # ---- 다운로드. **여기까지가 DoD 입니다** ---------------------------------------------
    # 링크가 보이는 것으로 끝내지 않습니다 - `download` 속성은 교차 출처에서 조용히 무시되고,
    # 그때 화면은 멀쩡한데 파일만 안 떨어집니다. 실제로 받아 봐야 그 차이가 드러납니다.
    with page.expect_download(timeout=RESULT_TIMEOUT_MS) as download_info:
        page.get_by_role("link", name="이미지 저장").click()
    download = download_info.value
    assert download.suggested_filename.endswith(".webp"), download.suggested_filename
    assert download.path().stat().st_size > 0

    # ---- 새로고침해도 같은 자리입니다 ---------------------------------------------------
    # `sessionId` 는 URL 에, `jobId` 는 세션에 있으므로 화면이 아무것도 보관하지 않아도
    # 복원됩니다. 이것이 깨지면 사용자는 결과를 받기 전에 창을 닫을 수 없습니다.
    page.reload()
    expect(result_image).to_be_visible(timeout=RESULT_TIMEOUT_MS)
