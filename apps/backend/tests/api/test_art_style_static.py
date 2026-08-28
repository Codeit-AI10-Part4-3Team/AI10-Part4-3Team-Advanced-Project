"""화풍 예시를 내주는 정적 마운트 (`/static/art-styles`).

⚠️ **이 경로는 backend 에서 유일하게 인증 밖에 있는 자산 경로입니다.** 그래서 여기 시험이
확인하는 것은 "파일이 나오는가" 보다 **무엇이 나오면 안 되는가** 쪽입니다 - 로그인 없이
열린다는 것, 상태 파일을 함께 열어 주지 않는다는 것, 그리고 디렉토리가 없어도 배포가
살아 있다는 것.

파일 자체는 커밋되지 않습니다 (구현_범위 4.3절). 그래서 시험은 임시 디렉토리에 가짜 바이트를
넣고 돌립니다 - 진짜 예시 8장은 사람이 볼륨에 넣습니다.
"""

from __future__ import annotations

import mimetypes
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

    ⚠️ **All three axes have to be *actually* siblings, and one of them is set somewhere
    else.** `log_dir` comes from the autouse `isolated_settings` fixture in `tests/conftest.py`,
    not from `env` above — same `tmp_path`, so they do line up today. The asserts below say so
    out loud because the alternative is a test that keeps passing after that fixture changes,
    while silently no longer measuring the axis it claims to (PR #208 리뷰, 정승호).
    """
    settings = deps.settings()
    # 세 축이 정말 `tmp_path` 밑에 나란히 있는지부터 봅니다. 픽스처가 하나라도 빠뜨리면
    # 그 축은 기본 상대 경로로 남고, 이 시험은 그것을 재지 않은 채 통과합니다.
    assert Path(settings.db_path).parent == env
    assert Path(settings.image_dir).parent == env
    assert Path(settings.log_dir).parent == env

    _check_art_style_dir(settings)


def test_the_type_does_not_depend_on_the_operating_system_mime_table(
    client: TestClient, env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⚠️ **같은 코드가 로컬에서는 맞고 컨테이너에서만 틀렸습니다** (이슈 #294).

    `.webp` 는 파이썬 3.12 의 내장 mimetypes 표에 없고, `python:3.12-slim` 에는
    `/etc/mime.types` 도 없습니다. 개발 기계에는 그 파일(윈도우는 레지스트리)이 있어 표가
    채워지므로, `guess_type` 에 맡기면 **배포에서만** `application/octet-stream` 이 나갑니다.

    아래가 그 컨테이너 조건을 그대로 만듭니다 - OS 표를 읽지 않은 내장 표로 `_db` 를 갈아
    끼우고, 그 표에서 `.webp` 도 걷어냅니다. 사설 이름을 쓰는 이유는 이것이 재현하려는 조건
    자체가 "OS 표가 없다" 이고, 공개 API 로는 그 상태를 만들 수 없기 때문입니다.

    ⚠️ **확장자를 걷어내는 줄을 지우지 마세요.** 파이썬 3.13 부터 `.webp` 가 내장 표에
    들어왔습니다. 그래서 "내장 표만 남긴다" 만으로는 조건이 만들어지지 않고, 3.13 이상
    개발 기계에서 이 시험이 **전제 단언에서 먼저 죽습니다** (실측: 3.14.5). 두 앱의
    `requires-python` 이 `>=3.12` 이므로 그 버전들도 규격 안입니다.

    걷어내는 쪽을 고른 이유는, 버전으로 건너뛰면 **3.13 이상에서는 이 시험이 아무것도
    재지 않게 되기** 때문입니다. 배포는 `python:3.12-slim` 이라 대상 코드
    (`mimetypes.add_type`)는 그대로 필요합니다.
    """
    db = mimetypes.MimeTypes(filenames=())
    for table in db.types_map:
        table.pop(".webp", None)
    monkeypatch.setattr(mimetypes, "_db", db)
    assert mimetypes.guess_type("style-01-traits.webp")[0] is None, (
        "이 시험이 재현하려는 조건은 'OS 표에도 내장 표에도 .webp 가 없다' 입니다"
    )

    styles = env / "art-styles"
    styles.mkdir()
    (styles / "style-01-traits.webp").write_bytes(WEBP)

    answer = client.get("/static/art-styles/style-01-traits.webp")

    assert answer.status_code == 200
    assert answer.headers["content-type"] == "image/webp"
