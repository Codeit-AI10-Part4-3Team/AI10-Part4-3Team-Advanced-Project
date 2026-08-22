"""화풍 예시를 내주는 정적 마운트 (`/static/art-styles`).

⚠️ **이 경로는 backend 에서 유일하게 인증 밖에 있는 자산 경로입니다.** 그래서 여기 시험이
확인하는 것은 "파일이 나오는가" 보다 **무엇이 나오면 안 되는가** 쪽입니다 - 로그인 없이
열린다는 것, 상태 파일을 함께 열어 주지 않는다는 것, 그리고 디렉토리가 없어도 배포가
살아 있다는 것.

파일 자체는 커밋되지 않습니다 (구현_범위 4.3절). 그래서 시험은 임시 디렉토리에 가짜 바이트를
넣고 돌립니다 - 진짜 예시 8장은 사람이 볼륨에 넣습니다.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from api import deps
from api.main import ART_STYLE_CACHE_CONTROL, _check_art_style_dir, app

PASSWORD = "correct-horse-battery-staple"  # noqa: S105 - a test fixture, never a deployed key
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 "


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    hasher = PasswordHasher()
    monkeypatch.setenv("ADGEN_DB_PATH", str(tmp_path / "sessions.sqlite"))
    monkeypatch.setenv("ADGEN_IMAGE_DIR", str(tmp_path / "images"))
    monkeypatch.setenv("ADGEN_ART_STYLE_DIR", str(tmp_path / "art-styles"))
    monkeypatch.setenv("ADGEN_SESSION_SECRET", "test-signing-key")
    monkeypatch.setenv(
        "ADGEN_ACCOUNTS",
        f'[{{"login_id": "demo1", "password_hash": "{hasher.hash(PASSWORD)}"}}]',
    )
    deps.settings.cache_clear()
    return tmp_path


@pytest.fixture
def client(env: Path) -> Iterator[TestClient]:
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


def test_an_example_is_served_without_logging_in(client: TestClient, env: Path) -> None:
    """⚠️ **The screen fetches these with a plain `<img>`, which carries no auth of its own.**

    A cookie would ride along on a same-origin `<img>`, so this could have been put behind
    `current_user` — but `StaticFiles` runs no route dependency, and turning it into a route
    would make it a `/v1` path and therefore contract surface (갈래 B, PR #194). The trade is
    deliberate: these eight files are our own product assets, not anyone's data.
    """
    styles = env / "art-styles"
    styles.mkdir()
    (styles / "style-01-traits.webp").write_bytes(WEBP)

    answer = client.get("/static/art-styles/style-01-traits.webp")

    assert answer.status_code == 200
    assert answer.content == WEBP
    assert answer.headers["cache-control"] == ART_STYLE_CACHE_CONTROL


def test_a_missing_directory_is_a_404_rather_than_a_dead_deployment(client: TestClient) -> None:
    """⚠️ The files are not committed (구현_범위 4.3절), so a fresh deployment has none.

    `StaticFiles` refuses to start when its directory is absent, which would take the whole
    stack down for an asset nobody has delivered yet.

    ⚠️ **A 404 is not the same as the screen's "예시 준비 중" placeholder.** `ArtStylePicker`
    branches on `exampleImageUrl === ""` alone and its `<img>` has no `onError`, so a filled
    URL with no file behind it draws a broken image instead. That is why the delivery order
    is fixed — files first, URLs second (infra/README.md). What #179 handles is the empty
    string, not the 404 (PR #208 리뷰, 신호정).
    """
    answer = client.get("/static/art-styles/style-01-traits.webp")

    assert answer.status_code == 404


def test_the_mount_cannot_be_pointed_at_the_state_directory(env: Path) -> None:
    """⚠️ **One shortened path would publish `adgen.sqlite` with no login.**

    `ADGEN_ART_STYLE_DIR=/data` puts the database, its account hashes and every uploaded
    photo under a URL that answers to anyone. Nothing downstream would notice: the stack is
    healthy, the screen works, and the exposure is silent until someone guesses the name.

    Refusing to start is the right answer here even though this repository usually prefers
    "keep serving" — staying up *is* the exposure, while a failed startup is seen by the
    person deploying, immediately.
    """
    settings = deps.settings()
    state = str(Path(settings.db_path).parent)
    # ⚠️ `log_dir` 이 셋째입니다. 자격 증명은 없지만 `app.log` 에 `sessionId` 와 트레이스백이
    # 30일치 있고, 인증 밖으로 내주면 그 기간에 대한 접근 범위가 사라집니다.

    for pointed_at in (state, str(Path(settings.image_dir)), str(Path(settings.log_dir))):
        with pytest.raises(RuntimeError, match="ADGEN_ART_STYLE_DIR"):
            _check_art_style_dir(settings.model_copy(update={"art_style_dir": pointed_at}))


def test_a_bad_directory_stops_the_app_from_starting(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⚠️ **The check above is only worth as much as the call site**, and the call site is
    one line in `lifespan` that nothing else touches.

    Deleting it leaves every other test green: the predicate keeps passing its own unit test
    while the deployment quietly serves the state directory. This starts the real app to pin
    that the two are connected (변이 시험으로 확인 - 이 시험 없이는 호출을 지워도 331건이
    전부 통과했습니다).
    """
    monkeypatch.setenv("ADGEN_ART_STYLE_DIR", str(Path(deps.settings().db_path).parent))
    deps.settings.cache_clear()

    with pytest.raises(RuntimeError, match="ADGEN_ART_STYLE_DIR"), TestClient(app):
        pass  # pragma: no cover - 기동이 여기 닿기 전에 멈춥니다


def test_a_sibling_directory_under_the_same_volume_is_fine(env: Path) -> None:
    """The deployment puts all four paths under one volume (ADR-0014), so the check has to
    refuse *containment* rather than the shared parent — otherwise it would refuse the only
    layout we actually ship.

    ⚠️ All three axes have to be *actually* siblings here, which is what the `ADGEN_LOG_DIR`
    line in the fixture buys. Without it `log_dir` keeps its relative default and this test
    passes while never having placed that axis beside the others — the direction it guards
    (a correct layout wrongly refused) would go unmeasured (PR #208 리뷰, 정승호).
    """
    settings = deps.settings()
    # 세 축이 정말 `tmp_path` 밑에 나란히 있는지부터 봅니다. 픽스처가 하나라도 빠뜨리면
    # 그 축은 기본 상대 경로로 남고, 이 시험은 그것을 재지 않은 채 통과합니다.
    assert Path(settings.db_path).parent == env
    assert Path(settings.image_dir).parent == env
    assert Path(settings.log_dir).parent == env

    _check_art_style_dir(settings)
