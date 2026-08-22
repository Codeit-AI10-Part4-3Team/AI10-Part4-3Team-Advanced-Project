#!/usr/bin/env python3
"""Dev-environment doctor: diagnose -> confirm -> repair -> re-verify.

Invoked through scripts/setup-dev.sh (macOS/Linux/WSL/Git Bash) or scripts/setup-dev.ps1
(Windows PowerShell). Both wrappers are intentionally trivial so the check registry lives
here only -- two hand-written implementations would drift within a sprint.

Compatibility: this file must stay parseable on Python 3.8+. The project requires 3.12 and
reporting that requirement is this script's job; a SyntaxError on an older interpreter would
swallow the very diagnosis the user needs.

Failure codes (E01.., W01..) map 1:1 to docs/공통_가이드/환경_세팅_가이드.md sections.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

DOC = "docs/공통_가이드/환경_세팅_가이드.md"

OK = "OK"
MISSING = "MISSING"
BROKEN = "BROKEN"
SKIP = "SKIP"

# Levels decide the exit code; scopes decide whether a check applies to the current mode.
BLOCK = "BLOCK"  # cannot continue -- abort immediately
FIX = "FIX"  # required, auto-repairable
WARN = "WARN"  # optional tooling; never fails the run

SCOPE_ALWAYS = "always"
SCOPE_PYTHON = "python"  # interpreter / dependency state
SCOPE_HOST = "host"  # git hooks and secrets defence -- run on the machine that commits


# ---------------------------------------------------------------- output helpers


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR") is not None or not sys.stdout.isatty():
        return False
    if os.name == "nt":
        return bool(os.environ.get("WT_SESSION") or os.environ.get("TERM"))
    return True


_COLOR = _supports_color()


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def head(text: str) -> None:
    print("\n" + _c(text, "1"))


# ASCII markers on purpose: the Windows console defaults to cp949 for this team, and box
# drawing / warning glyphs raise UnicodeEncodeError there.
MARK = {OK: "[ OK ]", MISSING: "[ !! ]", BROKEN: "[ !! ]", SKIP: "[ -- ]"}


def line(status: str, code: str, title: str, detail: str = "") -> None:
    color = {OK: "32", MISSING: "31", BROKEN: "31", SKIP: "90"}[status]
    tail = f"  {detail}" if detail else ""
    print("{} {:<4} {}{}".format(_c(MARK[status], color), code, title, _c(tail, "90")))


# ---------------------------------------------------------------- process helpers


def run(cmd, cwd=None, capture=True):
    """Run a command without a shell; never raises on non-zero exit."""
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        text=True,
    )


def ok(cmd, cwd=None) -> bool:
    try:
        return run(cmd, cwd=cwd).returncode == 0
    except (OSError, ValueError):
        return False


def out(cmd, cwd=None) -> str:
    try:
        proc = run(cmd, cwd=cwd)
    except (OSError, ValueError):
        return ""
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def has_module(name: str) -> bool:
    return ok([sys.executable, "-c", "import " + name])


def pip_install(*args: str) -> bool:
    print(_c("     $ pip install " + " ".join(args), "90"))
    return run([sys.executable, "-m", "pip", "install", *args], capture=False).returncode == 0


def _is_wsl_shim(path: str) -> bool:
    """True for System32\\bash.exe -- the WSL launcher, not a usable Windows bash.

    It runs inside the Linux distro, so it neither understands the Windows path we would
    hand it nor sees the Windows venv that owns ruff/mypy/pytest.
    """
    if os.name != "nt":
        return False
    # Upper-case names: os.environ normalises Windows keys to upper case, so "SYSTEMROOT"
    # and "SystemRoot" resolve identically -- and only the former satisfies SIM112.
    windir = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR") or "C:\\Windows"
    try:
        resolved = os.path.normcase(os.path.realpath(path))
    except OSError:
        resolved = os.path.normcase(path)
    # Trailing separator is load-bearing: without it "C:\WindowsApps\bash.exe" would match.
    prefix = os.path.normcase(windir).rstrip(os.sep) + os.sep
    return resolved.startswith(prefix)


def _git_bash_candidates():
    """Git for Windows ships bash.exe next to git.exe (…\\Git\\cmd → …\\Git\\bin)."""
    git = shutil.which("git")
    if git:
        bindir = Path(git).resolve().parent
        yield bindir / "bash.exe"  # PATH points at …\Git\bin
        install = bindir.parent  # PATH points at …\Git\cmd
        yield install / "bin" / "bash.exe"
        yield install / "usr" / "bin" / "bash.exe"
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            yield Path(base) / "Git" / "bin" / "bash.exe"


def find_bash():
    """Locate a bash that shares this interpreter's environment.

    Returns (path, kind) with kind in {"native", "gitbash", "wsl", None}. On Windows
    `which("bash")` usually resolves to the WSL shim, which is reported as "wsl" rather
    than returned as usable -- see docs §W05.
    """
    found = shutil.which("bash")
    if found and not _is_wsl_shim(found):
        return found, "native"
    if os.name == "nt":
        for candidate in _git_bash_candidates():
            if candidate.is_file():
                return str(candidate), "gitbash"
    return (found, "wsl") if found else (None, None)


# ---------------------------------------------------------------- context


class Ctx:
    def __init__(self, root: Path, mode: str, auto_yes: bool, check_only: bool) -> None:
        self.root = root
        self.mode = mode
        self.auto_yes = auto_yes
        self.check_only = check_only
        self.needs_restart = False  # a repair that only takes effect in a fresh shell

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)


def detect_mode(explicit: str) -> str:
    if explicit != "auto":
        return explicit
    env = os.environ.get("PROJECT_ENV_MODE", "").strip().lower()
    if env in ("host", "docker", "container"):
        return env
    if Path("/.dockerenv").exists():
        return "container"
    try:
        cgroup = Path("/proc/1/cgroup").read_text(errors="ignore")
    except OSError:
        cgroup = ""
    if "docker" in cgroup or "containerd" in cgroup:
        return "container"
    return "host"


def find_root() -> Path:
    top = out(["git", "rev-parse", "--show-toplevel"], cwd=Path(__file__).resolve().parent)
    return Path(top) if top else Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- checks


class Check:
    def __init__(self, code, title, scope, level, probe, fix=None, hint=""):
        self.code = code
        self.title = title
        self.scope = scope
        self.level = level
        self.probe = probe
        self.fix = fix
        self.hint = hint

    def effective_level(self, ctx: Ctx) -> str:
        # In docker mode the container owns the Python side; keep reporting it, stop failing on it.
        if ctx.mode == "docker" and self.scope == SCOPE_PYTHON and self.level == FIX:
            return WARN
        return self.level

    def applies(self, ctx: Ctx) -> bool:
        # Hooks fire on the machine running `git commit`, which is never the container.
        return not (ctx.mode == "container" and self.scope == SCOPE_HOST)


# --- E01 git ------------------------------------------------------


def probe_git(ctx):
    if not shutil.which("git"):
        return MISSING, "git 실행 파일 없음"
    if not ok(["git", "rev-parse", "--git-dir"], cwd=ctx.root):
        return BROKEN, "git 저장소가 아님"
    return OK, out(["git", "--version"], cwd=ctx.root)


# --- E02 python version -------------------------------------------


def probe_python(ctx):
    version = "{}.{}.{}".format(*sys.version_info[:3])
    if sys.version_info < (3, 12):
        return BROKEN, f"{version} — 3.12 이상 필요"
    return OK, f"{version} ({sys.executable})"


# --- E03 isolated interpreter -------------------------------------


def probe_isolation(ctx):
    if ctx.mode == "container":
        return OK, "컨테이너 내부 — 이미지가 격리를 담당"
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        return OK, f"venv: {sys.prefix}"
    conda = os.environ.get("CONDA_PREFIX")
    name = os.environ.get("CONDA_DEFAULT_ENV", "")
    if conda and name and name != "base":
        return OK, f"conda: {name}"
    if conda:
        return BROKEN, "conda base 활성 — 프로젝트 전용 env 필요"
    return MISSING, "시스템 파이썬 — 격리 환경 없음"


def fix_isolation(ctx):
    if os.environ.get("CONDA_PREFIX"):
        # Creating a venv on top of conda base works but produces a confusing hybrid;
        # the conda-native path is the user's call, not ours.
        print("     conda 사용 중이므로 자동 생성하지 않습니다. 아래를 직접 실행하세요:")
        print("       conda create -n adgen python=3.12 && conda activate adgen")
        ctx.needs_restart = True
        return False
    venv = ctx.path(".venv")
    if not venv.exists():
        print(_c(f"     $ {sys.executable} -m venv .venv", "90"))
        if run([sys.executable, "-m", "venv", str(venv)], capture=False).returncode != 0:
            return False
    activate = r".venv\Scripts\activate" if os.name == "nt" else "source .venv/bin/activate"
    print("     .venv 생성 완료. 활성화 후 이 스크립트를 다시 실행하세요:")
    print(f"       {activate}")
    ctx.needs_restart = True
    return False


# --- E04 editable installs ----------------------------------------


APP_MODULES = ("api", "backend_core", "ai_engine")

# Resolve each module in the *target* interpreter and report where it actually came from.
# Importing (rather than find_spec) is deliberate: it reproduces what pytest does, so a package
# that resolves but explodes on import is reported as missing rather than silently passing.
_LOCATE = (
    "import json,sys\n"
    "out={}\n"
    "for n in sys.argv[1:]:\n"
    "    try:\n"
    "        out[n]=getattr(__import__(n),'__file__','') or ''\n"
    "    except Exception:\n"
    "        out[n]=''\n"
    "print(json.dumps(out))\n"
)


def module_origins(names):
    raw = out([sys.executable, "-c", _LOCATE, *names])
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


# List every sys.path entry that *could* serve one of our module names, not just the winner.
# An editable install is a plain directory entry, so two checkouts coexist happily and site.py
# picks by sorted .pth filename -- see shadow_installs() for why that matters.
_SHADOW = (
    "import json,sys\n"
    "from pathlib import Path\n"
    "hits=[]\n"
    "for entry in sys.path:\n"
    "    if not entry:\n"
    "        continue\n"
    "    base=Path(entry)\n"
    "    for n in sys.argv[1:]:\n"
    "        if (base/n/'__init__.py').exists() or (base/(n+'.py')).exists():\n"
    "            hits.append([str(base),n])\n"
    "print(json.dumps(hits))\n"
)


def under(root: Path, candidate: str) -> bool:
    # Path.is_relative_to() is 3.9+; this file must stay parseable on 3.8.
    try:
        Path(candidate).resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


def shadow_installs(root: Path):
    """Foreign checkouts of this template sharing the interpreter, winner or not.

    Editable installs put their src/ on sys.path as an ordinary directory entry, and site.py
    adds them in sorted .pth filename order. Two checkouts therefore coexist for weeks with
    whichever distribution name sorts first quietly winning -- the origin check below sees only
    that winner and reports OK. The loser takes over the moment anything uninstalls or renames
    the winner, and the ImportError/ValidationError it produces reads like a defect in this repo
    (measured 2026-08-22: `adgen-*` was shadowing another checkout's `savers-*`, not the reverse).

    Returns "<path> (<module>)" for each entry outside this checkout, one line per path.
    """
    raw = out([sys.executable, "-c", _SHADOW, *APP_MODULES])
    try:
        hits = json.loads(raw)
    except ValueError:
        return []
    found, seen = [], set()
    for entry, name in hits:
        if entry in seen or under(root, entry):
            continue
        seen.add(entry)
        found.append(f"{entry} ({name})")
    return found


def probe_editable(ctx):
    origins = module_origins(APP_MODULES)
    missing = [m for m in APP_MODULES if not origins.get(m)]
    if missing:
        return MISSING, "import 실패: {}".format(", ".join(missing))
    if ctx.mode == "container":
        # The image owns the environment and installs non-editable, so landing in site-packages
        # is by design here -- "outside the checkout" carries no signal.
        return OK, " / ".join(APP_MODULES)
    # Importable is not enough. Another checkout of this template installed editable into the
    # same interpreter satisfies `import ai_engine` while serving a foreign source tree, and the
    # resulting ImportError/ValidationError reads like a defect in this repo.
    foreign = [m for m in APP_MODULES if not under(ctx.root, origins[m])]
    if foreign:
        detail = ", ".join(f"{m} -> {origins[m]}" for m in foreign)
        return BROKEN, "이 체크아웃 밖을 import 중: " + detail
    shadows = shadow_installs(ctx.root)
    if shadows:
        return BROKEN, "다른 체크아웃이 같은 인터프리터에 함께 설치됨: " + ", ".join(shadows)
    return OK, " / ".join(APP_MODULES)


def fix_editable(ctx):
    # A shadow is not repaired by installing this repo again -- both entries would still be on
    # sys.path, and reinstalling only re-rolls the sorted-name lottery. Removing another
    # checkout's distribution from a shared interpreter is the operator's call, not the doctor's,
    # so print the exact commands and fail the check instead of guessing which one to drop.
    shadows = shadow_installs(ctx.root)
    if shadows:
        print("     같은 인터프리터에 다른 체크아웃이 설치돼 있어 자동 복구하지 않습니다:")
        for item in shadows:
            print(f"       - {item}")
        print(f"     확인: {sys.executable} -m pip list")
        print(f"     제거: {sys.executable} -m pip uninstall <배포판_이름>")
        print("     그 체크아웃은 자기 .venv 에서 설치하세요 (레포마다 .venv 하나).")
        return False
    backend = "{}[dev]".format(ctx.path("apps", "backend"))
    ai = "{}[dev]".format(ctx.path("apps", "ai-engine"))
    return pip_install("-e", backend, "-e", ai)


# --- E05 core.hooksPath -------------------------------------------


def probe_hookspath(ctx):
    value = out(["git", "config", "--get", "core.hooksPath"], cwd=ctx.root)
    if value:
        return BROKEN, f"core.hooksPath={value} — pre-commit 설치가 무력화됨"
    return OK, "미설정 (정상)"


def fix_hookspath(ctx):
    return ok(["git", "config", "--unset", "core.hooksPath"], cwd=ctx.root)


# --- E06 pre-commit -----------------------------------------------


def tool_cmd(module: str, executable: str):
    """Resolve a CLI, preferring the *current* interpreter's module over whatever is on PATH.

    On a machine with conda + venv, `shutil.which()` frequently resolves to the other
    environment's copy. That silently breaks two things: `python -m pre_commit` fails when the
    module lives elsewhere, and `nbstripout --install` writes a git filter pinned to an
    interpreter path that this checkout may not have. Current interpreter first, PATH second.
    """
    if has_module(module):
        return [sys.executable, "-m", module]
    found = shutil.which(executable)
    return [found] if found else None


def probe_precommit(ctx):
    cmd = tool_cmd("pre_commit", "pre-commit")
    if cmd is None:
        return MISSING, "pre-commit 미설치"
    return OK, out([*cmd, "--version"], cwd=ctx.root) or "설치됨"


def fix_precommit(ctx):
    return pip_install("pre-commit")


def _hook_installed(ctx: Ctx, name: str) -> bool:
    hook = ctx.path(".git", "hooks", name)
    if not hook.exists():
        return False
    try:
        return "pre-commit" in hook.read_text(errors="ignore")
    except OSError:
        return False


def _hook_stale_interpreter(ctx: Ctx, name: str) -> str:
    """Return the pinned interpreter path when the hook can no longer run, else "".

    `pre-commit install` bakes INSTALL_PYTHON (an absolute path) into the hook and falls back
    to `pre-commit` on PATH when that path is gone. Recreating the environment therefore leaves
    a hook that is *present* but only works if PATH happens to carry pre-commit -- otherwise
    every commit dies with `pre-commit: command not found`, and E07/E08 would still report OK.
    E09 already guards the same failure for the nbstripout filter; this keeps the pair honest.
    """
    hook = ctx.path(".git", "hooks", name)
    try:
        lines = hook.read_text(errors="ignore").splitlines()
    except OSError:
        return ""
    pinned = ""
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("INSTALL_PYTHON="):
            pinned = stripped.split("=", 1)[1].strip().strip('"').strip("'")
            break
    if not pinned or Path(pinned).exists():
        return ""
    # The hook's fallback is literally `exec pre-commit`, so PATH -- not this interpreter's
    # module -- decides whether it still runs. Checking the module here would hand back a
    # false OK for the exact case this probe exists to catch.
    return "" if shutil.which("pre-commit") else pinned


def _install_hook(ctx: Ctx, hook_type: str) -> bool:
    cmd = tool_cmd("pre_commit", "pre-commit")
    if cmd is None:
        print("     pre-commit이 이 인터프리터에 없습니다 — E06을 먼저 복구하세요.")
        return False
    cmd = [*cmd, "install"]
    if hook_type != "pre-commit":
        cmd += ["--hook-type", hook_type]
    return run(cmd, cwd=ctx.root, capture=False).returncode == 0


# --- E07 / E08 hooks ----------------------------------------------


def probe_commit_hook(ctx):
    if not _hook_installed(ctx, "pre-commit"):
        return MISSING, "미등록"
    stale = _hook_stale_interpreter(ctx, "pre-commit")
    if stale:
        return BROKEN, f"훅이 사라진 인터프리터를 가리킴: {stale}"
    return OK, ".git/hooks/pre-commit"


def fix_commit_hook(ctx):
    return _install_hook(ctx, "pre-commit")


def probe_push_hook(ctx):
    if not _hook_installed(ctx, "pre-push"):
        return MISSING, "미등록 — pytest 게이트가 로컬에서 동작하지 않음"
    stale = _hook_stale_interpreter(ctx, "pre-push")
    if stale:
        return BROKEN, f"훅이 사라진 인터프리터를 가리킴: {stale}"
    return OK, ".git/hooks/pre-push (pytest 게이트)"


def fix_push_hook(ctx):
    return _install_hook(ctx, "pre-push")


# --- E09 nbstripout filter ----------------------------------------


def probe_nbstripout(ctx):
    # .gitattributes declares `filter=nbstripout`, but git silently ignores a filter that has
    # no driver in config -- notebook outputs would be committed with nothing complaining.
    clean = out(["git", "config", "--get", "filter.nbstripout.clean"], cwd=ctx.root)
    if not clean:
        return MISSING, "git filter 미등록 — .gitattributes가 무시됨"
    # The driver pins an absolute interpreter path; a deleted env leaves a filter that fails
    # on every notebook checkout/commit instead of stripping.
    interpreter = clean.split()[0].strip('"')
    if Path(interpreter).is_absolute() and not Path(interpreter).exists():
        return BROKEN, f"필터가 사라진 인터프리터를 가리킴: {interpreter}"
    return OK, clean


def fix_nbstripout(ctx):
    # No PATH fallback here (unlike pre-commit): `--install` bakes the *running* interpreter's
    # absolute path into the git filter driver, so borrowing another env's nbstripout would pin
    # the filter to an interpreter this project does not use.
    if not has_module("nbstripout") and not pip_install("nbstripout"):
        return False
    # `--install` writes .git/info/attributes and the filter driver; the tracked .gitattributes
    # is left untouched on purpose.
    return (
        run(
            [sys.executable, "-m", "nbstripout", "--install"], cwd=ctx.root, capture=False
        ).returncode
        == 0
    )


# --- E10 hook environments ----------------------------------------


def probe_hook_envs(ctx):
    cache = Path(os.environ.get("PRE_COMMIT_HOME") or Path.home() / ".cache" / "pre-commit")
    if cache.exists() and any(cache.iterdir()):
        return OK, str(cache)
    return MISSING, "훅 환경 미생성 — 첫 커밋이 수 분간 멈춤"


def fix_hook_envs(ctx):
    cmd = tool_cmd("pre_commit", "pre-commit")
    if cmd is None:
        return False
    print("     훅 환경을 내려받습니다 (최초 1회, 수 분 소요)")
    return run([*cmd, "install-hooks"], cwd=ctx.root, capture=False).returncode == 0


# --- E11 infra/.env -----------------------------------------------


def probe_env_file(ctx):
    env = ctx.path("infra", ".env")
    if not env.exists():
        return MISSING, "infra/.env 없음"
    # A committed key on a public repo is a one-way door; verify the ignore actually matches.
    if not ok(["git", "check-ignore", "-q", str(env)], cwd=ctx.root):
        return BROKEN, "infra/.env가 git에 추적될 수 있음 — .gitignore 확인 필요"
    return OK, "존재 + git 무시됨"


def fix_env_file(ctx):
    sample = ctx.path("infra", ".env.example")
    if not sample.exists():
        print("     infra/.env.example 이 없습니다 — 수동 확인 필요")
        return False
    shutil.copyfile(str(sample), str(ctx.path("infra", ".env")))
    print("     infra/.env 생성 (값은 비어 있음 — 발급받은 키를 직접 채우세요)")
    return True


# --- E12 line endings ---------------------------------------------


# Discovered, not listed. A hardcoded tuple silently stops covering a script the moment
# someone adds one — it had already drifted past scripts/apply-labels.sh. Every .sh in the
# repo lives under scripts/, so a single glob is enough and costs no subprocess or tree walk.
SHELL_DIR = "scripts"


def _shell_files(ctx: Ctx):
    # The glob only discovers names; each path is then re-derived from the literal root and
    # required to resolve back into it. fix_line_endings rewrites bytes in place, so without
    # this a symlink dropped into scripts/ would have it edit a file anywhere on disk -- a
    # risk the previous hardcoded tuple did not carry. (Sonar flags the same shape as S2083.)
    root = ctx.path(SHELL_DIR)
    try:
        resolved_root = root.resolve()
        names = sorted(p.name for p in root.glob("*.sh"))
    except OSError:
        return []
    files = []
    for name in names:
        path = root / name
        try:
            if path.resolve().parent == resolved_root and path.is_file():
                files.append(path)
        except OSError:
            continue
    return files


def _crlf_paths(ctx: Ctx):
    bad = []
    for path in _shell_files(ctx):
        try:
            if b"\r\n" in path.read_bytes():
                bad.append(path)
        except OSError:
            continue
    return bad


def _crlf_files(ctx: Ctx):
    return [p.relative_to(ctx.root).as_posix() for p in _crlf_paths(ctx)]


def probe_line_endings(ctx):
    bad = _crlf_files(ctx)
    if bad:
        return BROKEN, "CRLF 개행: {} — bash가 '\\r' 오류로 실패".format(", ".join(bad))
    return OK, "LF 정상"


def fix_line_endings(ctx):
    # autocrlf=input keeps LF in the working tree while still normalising on commit.
    ok(["git", "config", "core.autocrlf", "input"], cwd=ctx.root)
    # The bytes are rewritten directly rather than via git checkout on purpose: the blobs
    # in the repo are already LF, so git sees no difference to restore and leaves a CRLF
    # working copy untouched (`git status` stays clean while bash keeps failing).
    for path in _crlf_paths(ctx):
        try:
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
        except OSError:
            return False
    return True


# --- W01..W05 optional tooling ------------------------------------


def probe_gh(ctx):
    if not shutil.which("gh"):
        return MISSING, "gh CLI 없음 (admin의 setup-github.sh 실행에만 필요)"
    if not ok(["gh", "auth", "status"]):
        return BROKEN, "gh 미인증 — gh auth login"
    return OK, "인증됨"


def probe_docker(ctx):
    if not shutil.which("docker"):
        return MISSING, "docker 없음 (인프라·통합 실행 시 필요)"
    if not ok(["docker", "compose", "version"]):
        return BROKEN, "docker compose v2 없음"
    return OK, out(["docker", "--version"])


def probe_node(ctx):
    if not shutil.which("node"):
        return MISSING, "node 없음 (apps/frontend 작업 시 필요)"
    return OK, out(["node", "--version"])


def probe_e2e(ctx):
    if not has_module("playwright"):
        return MISSING, "e2e 의존성 없음 — pip install -r e2e/requirements.txt (QA)"
    return OK, "playwright 설치됨"


def probe_bash(ctx):
    path, kind = find_bash()
    if kind == "wsl":
        return MISSING, f"WSL bash만 있음 — Windows venv를 못 봄({DOC}#w05)"
    if not path:
        return MISSING, "bash 없음 — run-tests.sh(로컬 CI)를 실행할 수 없음"
    return OK, path


CHECKS = [
    Check(
        "E01",
        "git 사용 가능 + 저장소 인식",
        SCOPE_ALWAYS,
        BLOCK,
        probe_git,
        hint="git을 설치하고 저장소를 clone한 위치에서 실행하세요.",
    ),
    Check(
        "E02",
        "Python 3.12 이상",
        SCOPE_ALWAYS,
        BLOCK,
        probe_python,
        hint="conda: conda create -n adgen python=3.12 / 그 외: python.org 3.12+ 설치",
    ),
    Check(
        "E03",
        "격리된 파이썬 환경 (venv·conda·컨테이너)",
        SCOPE_PYTHON,
        FIX,
        probe_isolation,
        fix_isolation,
    ),
    Check("E04", "앱 editable 설치", SCOPE_PYTHON, FIX, probe_editable, fix_editable),
    Check("E05", "core.hooksPath 충돌 없음", SCOPE_HOST, FIX, probe_hookspath, fix_hookspath),
    Check("E06", "pre-commit 설치", SCOPE_HOST, FIX, probe_precommit, fix_precommit),
    Check("E07", "pre-commit 훅 등록", SCOPE_HOST, FIX, probe_commit_hook, fix_commit_hook),
    Check("E08", "pre-push 훅 등록", SCOPE_HOST, FIX, probe_push_hook, fix_push_hook),
    Check("E09", "nbstripout git filter 등록", SCOPE_HOST, FIX, probe_nbstripout, fix_nbstripout),
    Check("E10", "pre-commit 훅 환경 캐시", SCOPE_HOST, FIX, probe_hook_envs, fix_hook_envs),
    Check("E11", "infra/.env 존재 + git 무시", SCOPE_HOST, FIX, probe_env_file, fix_env_file),
    Check("E12", "셸 스크립트 개행(LF)", SCOPE_HOST, FIX, probe_line_endings, fix_line_endings),
    Check("W01", "gh CLI 인증 (admin)", SCOPE_ALWAYS, WARN, probe_gh),
    Check("W02", "docker + compose v2 (인프라)", SCOPE_ALWAYS, WARN, probe_docker),
    Check("W03", "Node.js (프론트엔드)", SCOPE_ALWAYS, WARN, probe_node),
    Check("W04", "e2e 의존성 (QA)", SCOPE_ALWAYS, WARN, probe_e2e),
    Check("W05", "bash 사용 가능", SCOPE_ALWAYS, WARN, probe_bash),
]


# ---------------------------------------------------------------- runner


def confirm(ctx: Ctx, question: str) -> bool:
    if ctx.auto_yes:
        return True
    if not sys.stdin.isatty():
        print("     (비대화 환경: 자동 설치를 건너뜁니다 — --yes 로 강제할 수 있습니다)")
        return False
    try:
        answer = input(f"     {question} [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("", "y", "yes")


def evaluate(ctx: Ctx):
    results = []
    for check in CHECKS:
        if not check.applies(ctx):
            results.append((check, SKIP, "컨테이너 모드 — 호스트 항목"))
            continue
        status, detail = check.probe(ctx)
        results.append((check, status, detail))
        if status != OK and check.level == BLOCK:
            break
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="개발 환경 점검·복구",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="자세한 오류 대처: " + DOC,
    )
    parser.add_argument("--check", action="store_true", help="진단만 수행 (변경 없음)")
    parser.add_argument("--yes", action="store_true", help="확인 프롬프트 없이 전부 복구")
    parser.add_argument("--skip-tests", action="store_true", help="마지막 로컬 CI 실행 생략")
    parser.add_argument(
        "--mode",
        default="auto",
        choices=["auto", "host", "docker", "container"],
        help="auto=자동 감지, docker=컨테이너 개발(파이썬 항목 경고로 강등), container=컨테이너 내부",
    )
    args = parser.parse_args()

    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    ctx = Ctx(find_root(), detect_mode(args.mode), args.yes, args.check)

    head("개발 환경 점검")
    print(f"  경로: {ctx.root}")
    print(f"  모드: {ctx.mode}   플랫폼: {sys.platform}   파이썬: {sys.executable}")

    head("1. 진단")
    results = evaluate(ctx)
    for check, status, detail in results:
        line(status, check.code, check.title, detail)

    blocked = [r for r in results if r[1] != OK and r[0].level == BLOCK]
    if blocked:
        head("중단: 자동 복구할 수 없는 전제 조건")
        for check, _, _ in blocked:
            print(f"  [{check.code}] {check.hint}")
            print(f"       {DOC}#{check.code.lower()}")
        return 2

    repairable = [
        r for r in results if r[1] in (MISSING, BROKEN) and r[0].fix and r[0].level == FIX
    ]
    attempted = False
    if repairable and not ctx.check_only:
        head("2. 복구")
        for check, _, _ in repairable:
            print(f"  [{check.code}] {check.title}")
            if not confirm(ctx, "복구할까요?"):
                print("     건너뜀")
                continue
            attempted = True
            if not check.fix(ctx):
                print(f"     복구 실패 — {DOC}#{check.code.lower()}")
    elif repairable:
        head("2. 복구 (--check: 생략)")

    # Re-probe only when something was actually repaired -- otherwise the second table is
    # a verbatim copy of the first and just buries the summary.
    if attempted:
        head("3. 재점검")
        results = evaluate(ctx)
        for check, status, detail in results:
            line(status, check.code, check.title, detail)

    failed = [r for r in results if r[1] in (MISSING, BROKEN) and r[0].effective_level(ctx) == FIX]
    warned = [r for r in results if r[1] in (MISSING, BROKEN) and r[0].effective_level(ctx) == WARN]

    if warned:
        head("선택 항목 (실패 아님)")
        for check, _, detail in warned:
            print(f"  [{check.code}] {check.title} — {detail}")

    if failed:
        head("남은 문제")
        for check, _, _ in failed:
            print(f"  [{check.code}] {check.title}  ->  {DOC}#{check.code.lower()}")
        return 2 if ctx.needs_restart else 1

    if ctx.needs_restart:
        head("셸 재시작 필요")
        print("  환경을 활성화한 뒤 이 스크립트를 다시 실행하세요.")
        return 2

    if args.skip_tests or ctx.check_only:
        head("완료: 환경 정상 (로컬 CI 실행은 생략)")
        return 0

    head("4. 로컬 CI 등가성 확인 (scripts/run-tests.sh)")
    bash, kind = find_bash()
    if kind == "wsl":
        print(f"  Windows에 WSL bash({bash})만 있어 실행하지 못했습니다.")
        print("  WSL bash는 별도 리눅스 배포판에서 돌아 이 venv(ruff·mypy·pytest)를 보지 못합니다.")
        print(f"  Git for Windows를 설치하거나, WSL 안에서 clone부터 다시 하세요 — {DOC}#w05")
        return 0
    if not bash:
        print("  bash가 없어 실행하지 못했습니다 — Git Bash 설치 또는 WSL에서 실행하세요.")
        print(f"  {DOC}#w05")
        return 0
    # Relative path on purpose: a Windows absolute path is not resolvable by every bash.
    code = run([bash, "scripts/run-tests.sh"], cwd=ctx.root, capture=False).returncode
    if code != 0:
        head("로컬 CI 실패 — 환경 문제가 아니라 코드/테스트 문제일 수 있습니다")
        return 1

    head("완료: 환경 정상 + 로컬 CI 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
