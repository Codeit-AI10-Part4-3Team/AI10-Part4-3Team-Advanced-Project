"""Shared fixtures for ai-engine tests.

Everything here runs offline: no model API, no embedding API, no network. External calls
in tests cost money and make CI non-deterministic (AGENTS.md).
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from ai_engine.retrieval import FixtureRetriever

# A question the bundled dummy corpus can actually answer. Keep it in sync with
# src/ai_engine/fixtures/corpus.jsonl — if the corpus changes and this does not, the
# tests start asserting on the refusal path without anyone noticing.
ANSWERABLE_QUESTION = "환불은 어떻게 하나요?"
UNANSWERABLE_QUESTION = "내일 주식 시장 전망을 알려주세요"

# tests/ -> apps/ai-engine/ -> apps/ -> repo root
CONTRACT_PATH = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "openapi.yaml"


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


@pytest.fixture
def retriever() -> FixtureRetriever:
    return FixtureRetriever.from_jsonl()
