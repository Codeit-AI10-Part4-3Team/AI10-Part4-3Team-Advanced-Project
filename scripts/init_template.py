#!/usr/bin/env python3
"""템플릿 초기화 — 새 프로젝트 이름으로 일괄 치환한 뒤 스스로를 삭제한다.

Usage:
    python3 scripts/init_template.py --name my-service --owner Yopkigom
    python3 scripts/init_template.py --name my-service --owner Yopkigom \\
        --repo my-service-repo --env-prefix MYSVC_

치환 내용:
    my-ai-project      -> --name        (배포판 이름: pyproject name, FastAPI title,
                                         docker 이미지 태그, compose 프로젝트명)
    MYAPP_             -> --env-prefix  (환경변수 접두어: config 클래스, compose, .env.example)
    {{GITHUB_OWNER}}   -> --owner       (이슈 config, CODEOWNERS, README 배지 URL)
    {{GITHUB_REPO}}    -> --repo        (기본값은 --name)

그 외:
    README.md          <- README.project.md 로 교체 (템플릿 소개 -> 프로젝트 README)
    scripts/init_template.py 자신을 삭제

⚠️ 이 스크립트는 **이름만** 바꿉니다. 내용(팀·계약·코퍼스·CODEOWNERS 계정)은 사람이 채워야
   하며, 그 목록은 docs/TEMPLATE_GUIDE.md §3에 있습니다.

파이썬 패키지 이름(`api` / `backend_core` / `ai_engine`)은 **치환하지 않습니다.** 앱 경계 규칙과
CI 설정이 그 이름을 참조하고 있어, 바꾸면 얻는 것 없이 고칠 곳만 늘어납니다.
"""

import argparse
import re
import sys
from pathlib import Path

DIST_PLACEHOLDER = "my-ai-project"
ENV_PLACEHOLDER = "MYAPP_"
OWNER_PLACEHOLDER = "{{GITHUB_OWNER}}"
REPO_PLACEHOLDER = "{{GITHUB_REPO}}"

ROOT = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve()
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".ipynb_checkpoints", "node_modules"}
# 템플릿 전용 문서는 치환 대상에서 제외한다 — 초기화 후에도 원문 그대로 읽을 수 있어야
# "무엇을 지워야 하는지"를 확인할 수 있다. README.md는 README.project.md로 대체된다.
SKIP_FILES = {
    SELF,
    ROOT / "README.md",
    ROOT / "docs" / "TEMPLATE_GUIDE.md",
    ROOT / "docs" / "DESIGN_DECISIONS.md",
}
TEMPLATE_ONLY_DOCS = ("docs/TEMPLATE_GUIDE.md", "docs/DESIGN_DECISIONS.md")


def iter_text_files(root: Path) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def replace_in_file(path: Path, table: dict[str, str]) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False  # binary file
    new_text = text
    for old, new in table.items():
        new_text = new_text.replace(old, new)
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False


def default_env_prefix(name: str) -> str:
    """my-service -> MYSERVICE_ . 환경변수 이름에 쓸 수 없는 문자는 밑줄로."""
    return re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_") + "_"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="배포판 이름 (예: my-service)")
    parser.add_argument("--owner", required=True, help="GitHub owner (계정/조직)")
    parser.add_argument("--repo", help="GitHub 리포 이름 (기본: --name)")
    parser.add_argument("--env-prefix", help="환경변수 접두어 (기본: --name 대문자 + '_')")
    args = parser.parse_args()

    name = args.name
    repo = args.repo or name
    env_prefix = args.env_prefix or default_env_prefix(name)

    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", name):
        parser.error(f"--name '{name}' 은 소문자/숫자/._- 만 허용합니다.")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*_", env_prefix):
        parser.error(f"--env-prefix '{env_prefix}' 는 대문자/숫자/_ 로 쓰고 '_'로 끝나야 합니다.")

    table = {
        DIST_PLACEHOLDER: name,
        ENV_PLACEHOLDER: env_prefix,
        OWNER_PLACEHOLDER: args.owner,
        REPO_PLACEHOLDER: repo,
    }

    changed = [p for p in iter_text_files(ROOT) if replace_in_file(p, table)]
    for p in changed:
        print(f"치환: {p.relative_to(ROOT)}")

    project_readme = ROOT / "README.project.md"
    if project_readme.exists():
        project_readme.replace(ROOT / "README.md")
        print("교체: README.md <- README.project.md")

    SELF.unlink()
    print("삭제: scripts/init_template.py")

    print(
        f"\n초기화 완료 (이름={name}, env 접두어={env_prefix}, 리포={args.owner}/{repo}).\n"
        "\n다음 단계:\n"
        "  1) bash scripts/setup-dev.sh          # Windows: powershell -File scripts\\setup-dev.ps1\n"
        "  2) python3 -m venv .venv && source .venv/bin/activate\n"
        '  3) pip install -e "./apps/backend[dev]" -e "./apps/ai-engine[dev]"\n'
        "  4) pip install pre-commit && pre-commit install && "
        "pre-commit install --hook-type pre-push\n"
        "  5) bash scripts/run-tests.sh          # 품질 게이트가 통과하는지 확인\n"
        f"  6) bash scripts/setup-github.sh {args.owner}/{repo} [--solo]   (gh 인증 필요)\n"
        "\n⚠️ 아직 남은 일 — 이름만 바뀌었을 뿐입니다:\n"
        "  · CODEOWNERS 의 예시 계정(@teammate-*)을 실제 GitHub ID로\n"
        "  · AGENTS.md 의 TODO 절 (프로젝트 개요·제약·지표·팀)\n"
        "  · packages/contracts/openapi.yaml 을 실제 계약으로\n"
        "  · apps/ai-engine/.../fixtures/corpus.jsonl 을 실제 코퍼스로\n"
        "  · 전체 목록: docs/TEMPLATE_GUIDE.md §3\n"
        f"  · 다 끝나면 템플릿 전용 문서 삭제: {', '.join(TEMPLATE_ONLY_DOCS)}\n"
        "\n  7) git add -A && git commit -m 'chore: init from ai-team-project-template'"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
