"""Shared fixtures for ai-engine tests.

Everything here runs offline: no model API, no embedding API, no network. External calls
in tests cost money and make CI non-deterministic (AGENTS.md).
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

# tests/ -> apps/ai-engine/ -> apps/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = REPO_ROOT / "packages" / "contracts" / "openapi.yaml"
ENV_EXAMPLE_PATH = REPO_ROOT / "infra" / ".env.example"


@pytest.fixture(scope="session")
def env_example() -> dict[str, str]:
    """`infra/.env.example` 의 값들. **호출자 쪽 설정을 볼 수 있는 유일한 자리입니다.**

    타임아웃은 두 앱에 걸친 **짝**이라(엔진이 먼저 포기한다), 한쪽만 보는 시험은 짝의 절반만
    고정합니다 - 호출자 값을 테스트에 상수로 적으면 `infra/.env` 가 그 값을 옮겨도 초록입니다
    (이슈 #180 리뷰). backend 를 import 할 수는 없으므로(AGENTS.md 아키텍처 경계) 커밋된 이
    파일이 양쪽을 함께 볼 수 있는 유일한 근거입니다.
    """
    if not ENV_EXAMPLE_PATH.exists():
        pytest.fail(f"{ENV_EXAMPLE_PATH} 가 없습니다 - 타임아웃 짝 시험이 돌 수 없습니다.")
    values: dict[str, str] = {}
    for raw in ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


@pytest.fixture(scope="session")
def contract_schemas() -> dict[str, Any]:
    """`components.schemas` from the contract, for the conformance tests.

    Read straight from the spec rather than copied into the test: a copy drifts with the
    models it is supposed to police, which is the failure this fixture exists to prevent.

    ⚠️ Fails rather than skips when the file is missing. The tests live in this repo, so
    they cannot run without the checkout that carries the contract — meaning a missing file
    is never an environment fact, only a broken path or a moved contract. Skipping there
    would turn off every conformance test and still show green, which is the exact failure
    mode this suite exists to prevent.
    """
    if not CONTRACT_PATH.exists():
        pytest.fail(
            f"contract not found at {CONTRACT_PATH} — the conformance tests cannot run. "
            "Did packages/contracts/openapi.yaml move, or did this app's depth change?"
        )
    spec: dict[str, Any] = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    schemas: dict[str, Any] = spec["components"]["schemas"]
    return schemas
