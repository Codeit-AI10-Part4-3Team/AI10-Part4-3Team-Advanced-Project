"""What this app *publishes* against what the contract *says*.

⚠️ A different question from the conformance tests in tests/backend_core/models/. Those
compare our pydantic models to the contract's schemas; this compares the `/openapi.json`
FastAPI generates to the contract's paths. Both can drift, and they drift in different ways:
a model gets a field renamed, while a route gets its **shape** wrong — a path parameter
named differently, a media type left to the default, a status code nobody documented.

The failure mode is always the same and it is the nasty one: **the wire stays correct while
the spec lies.** Nothing breaks in testing, in the browser, or in CI. It breaks for whoever
generates a client from the published document and gets names we never serve.
"""

from __future__ import annotations

from typing import Any

from api.main import app

BACKEND_TAGS = {"auth", "sessions", "jobs", "catalog"}

# The template question-and-answer path predates the ad contract and is scheduled for
# replacement, not documentation (API_계약.md 7.1절).
NOT_IN_THE_AD_CONTRACT = {"/v1/ask"}

METHODS = ("get", "post", "patch", "delete", "put")


def _contract_operations(schemas_spec: dict[str, Any]) -> set[str]:
    return {
        f"{method.upper()} {path}"
        for path, operations in schemas_spec["paths"].items()
        for method, operation in operations.items()
        if method in METHODS
        and (BACKEND_TAGS & set(operation.get("tags", [])) or path == "/health")
    }


def _published_operations() -> set[str]:
    published = app.openapi()["paths"]
    return {
        f"{method.upper()} {path}"
        for path, operations in published.items()
        for method in operations
        if method in METHODS and path not in NOT_IN_THE_AD_CONTRACT
    }


def test_every_contract_path_is_served(contract_spec: dict[str, Any]) -> None:
    assert _contract_operations(contract_spec) - _published_operations() == set()


def test_nothing_is_served_that_the_contract_does_not_describe(
    contract_spec: dict[str, Any],
) -> None:
    """The direction that catches a route somebody added without touching the contract —
    implementation ahead of contract, which is the order this repo forbids (AGENTS.md)."""
    assert _published_operations() - _contract_operations(contract_spec) == set()


def test_path_parameters_carry_the_contract_names(contract_spec: dict[str, Any]) -> None:
    """⚠️ Regression guard. The routes published `{session_id}` and `{job_id}` while the
    contract says `{sessionId}` and `{jobId}` (2026-08-14 실측).

    A path parameter's name never travels — `/v1/sessions/abc` is the same request either
    way — so every test passed, the browser worked and CI was green. Only a generated client
    would have found it, by producing argument names for parameters we never named.
    """
    contract_paths = {
        path for path in contract_spec["paths"] if "{" in path and path.startswith("/v1")
    }
    published_paths = set(app.openapi()["paths"])

    assert contract_paths <= published_paths
