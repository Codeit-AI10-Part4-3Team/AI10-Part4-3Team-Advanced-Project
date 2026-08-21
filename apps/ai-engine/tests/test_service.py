"""Contract conformance for the HTTP surface.

Asserts the wire shape promised by packages/contracts/openapi.yaml. Module behaviour is
covered in the per-seam test modules (test_brief_fill.py, test_draft_model.py, …).

⚠️ 질의응답(`/v1/generate`) 테스트 셋은 2026-08-20 에 그 라우트와 함께 삭제됐습니다. 남은
`test_only_contract_routes_are_served` 가 그 자리를 대신합니다 - 라우트가 되살아나면 여기서
실패합니다.
"""

import pytest
from fastapi.testclient import TestClient

from ai_engine.service import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_only_contract_routes_are_served(client: TestClient) -> None:
    """서빙하는 경로가 계약에 있는 것 넷과 `/health` 뿐입니다.

    ⚠️ 포함 검사가 아니라 **정확한 집합**입니다. 무엇이 있어도 되는지를 나열해야 누군가
    "디버깅용으로" 추가한 경로가 배포가 아니라 여기서 걸립니다 - 파이프라인 중간으로 호출자를
    불러들이는 것이 이 테스트가 막는 것입니다.

    `/health` 만 계약 밖입니다. 그것은 도메인 경로가 아니라 오케스트레이터가 보는 생존 신호라
    계약의 대상이 아닙니다.
    """
    assert set(client.get("/openapi.json").json()["paths"]) == {
        "/health",
        "/v1/brief:fill",
        "/v1/draft:generate",
        "/v1/draft:patch",
        "/v1/image:render",
    }
