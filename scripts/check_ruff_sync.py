#!/usr/bin/env python3
"""ruff 버전이 선언된 모든 곳이 같은 값인지 검사한다.

왜 필요한가: 이 레포는 같은 ruff를 **서로 다른 경로로** 설치한다.
  - pre-commit 훅       -> .pre-commit-config.yaml 의 rev
  - CI lint 잡          -> apps/<app>/pyproject.toml 의 dev extra `ruff==`
  - reviewdog 워크플로  -> .github/workflows/reviewdog.yml 의 RUFF_VERSION
ruff는 0.x라 마이너 업그레이드에서 기본 규칙셋 자체가 넓어진다. 한 곳만 올라가면
"로컬 훅은 통과했는데 CI는 실패"가 재현되고, 그 상태가 반복되면 팀은 훅을 무시하기
시작한다 — 이 레포의 품질 게이트가 서 있는 전제가 무너진다.

이 규약은 지금까지 주석으로만 존재했고, 실제로 Dependabot의 pip 업데이트가 pyproject만
올리면서 드리프트가 발생했다. 그래서 주석을 검사로 승격한다.

pre-commit local 훅으로 등록되어 있으므로 커밋 시점과 CI(pre-commit --all-files)
양쪽에서 돌아간다. 별도 CI 잡이 아니라서 required status check 목록은 건드리지 않는다.

단독 실행:  python3 scripts/check_ruff_sync.py
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PRE_COMMIT = ROOT / ".pre-commit-config.yaml"
PYPROJECTS = (
    ROOT / "apps" / "backend" / "pyproject.toml",
    ROOT / "apps" / "ai-engine" / "pyproject.toml",
)
REVIEWDOG = ROOT / ".github" / "workflows" / "reviewdog.yml"

# .pre-commit-config.yaml 에서 ruff-pre-commit 저장소 블록의 rev 만 집는다.
# repo: 줄 이후 처음 나오는 rev: 가 그 저장소의 것이라는 pre-commit 스키마 규약에 의존한다.
_RUFF_REV = re.compile(
    r"repo:\s*https://github\.com/astral-sh/ruff-pre-commit\s*\n\s*rev:\s*v?(?P<version>[0-9][0-9A-Za-z.\-]*)"
)
_RUFF_VERSION_ENV = re.compile(
    r"^\s*RUFF_VERSION:\s*[\"']?v?(?P<version>[0-9][0-9A-Za-z.\-]*)[\"']?\s*$", re.MULTILINE
)
_RUFF_PIN = re.compile(r"^ruff==(?P<version>.+)$")


def _read(path: Path) -> str:
    """읽기 실패를 '검사 통과'로 흘려보내지 않기 위해 예외를 그대로 올린다."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(
            f"[ruff-sync] 파일을 읽을 수 없습니다: {path.relative_to(ROOT)} ({exc})"
        ) from exc


def pre_commit_version() -> str:
    match = _RUFF_REV.search(_read(PRE_COMMIT))
    if match is None:
        raise SystemExit(
            f"[ruff-sync] {PRE_COMMIT.relative_to(ROOT)} 에서 ruff-pre-commit 의 rev 를 찾지 못했습니다. "
            "훅을 제거했다면 이 스크립트와 pre-commit 훅 등록도 함께 정리하세요."
        )
    return match.group("version")


def pyproject_version(path: Path) -> str:
    try:
        data = tomllib.loads(_read(path))
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"[ruff-sync] TOML 파싱 실패: {path.relative_to(ROOT)} ({exc})") from exc

    dev_deps = data.get("project", {}).get("optional-dependencies", {}).get("dev", [])
    for dep in dev_deps:
        match = _RUFF_PIN.match(str(dep).strip())
        if match is not None:
            return match.group("version")

    raise SystemExit(
        f"[ruff-sync] {path.relative_to(ROOT)} 의 dev extra 에 `ruff==<버전>` 핀이 없습니다. "
        "범위(>=)로 두면 CI가 매번 최신 ruff 를 끌어와 훅과 어긋납니다."
    )


def reviewdog_version() -> str | None:
    """reviewdog 워크플로는 선택 사항이다 — 없으면 검사 대상에서 빠진다."""
    if not REVIEWDOG.exists():
        return None
    match = _RUFF_VERSION_ENV.search(_read(REVIEWDOG))
    if match is None:
        raise SystemExit(
            f"[ruff-sync] {REVIEWDOG.relative_to(ROOT)} 에 RUFF_VERSION 이 없습니다. "
            "워크플로가 ruff 를 설치하지 않는다면 이 검사에서 제외하도록 스크립트를 고치세요."
        )
    return match.group("version")


def main() -> int:
    found: dict[str, str] = {str(PRE_COMMIT.relative_to(ROOT)): pre_commit_version()}
    for path in PYPROJECTS:
        found[str(path.relative_to(ROOT))] = pyproject_version(path)

    reviewdog = reviewdog_version()
    if reviewdog is not None:
        found[str(REVIEWDOG.relative_to(ROOT))] = reviewdog

    if len(set(found.values())) == 1:
        return 0

    width = max(len(name) for name in found)
    lines = "\n".join(f"  {name:<{width}}  {version}" for name, version in found.items())
    print(
        "[ruff-sync] ruff 버전이 어긋났습니다 — 같은 코드가 한쪽에서만 통과합니다.\n"
        f"{lines}\n\n"
        "모두 같은 값으로 맞춘 뒤 다시 커밋하세요. Dependabot 이 한 곳만 올린 PR 이라면\n"
        "그 PR 안에서 나머지 파일도 함께 고치면 됩니다.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
