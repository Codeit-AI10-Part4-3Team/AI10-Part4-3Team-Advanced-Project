"""Shared fixtures.

Every test runs fully offline. The AI engine is replaced with a fake through FastAPI's
dependency overrides — external calls in tests cost money, are rate-limited and make CI
non-deterministic (AGENTS.md).

⚠️ The fake mimics the engine's *contract*, including both failure modes: a refusal
(`generate` returns `None`) and an outage (raises). It does not bypass the guardrail —
guardrail behaviour is tested in apps/ai-engine, where it lives.
"""

import os
import struct
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from api import deps
from api.main import app
from backend_core.ai_client import AiEngineUnavailableError
from backend_core.models import (
    BriefFillResponse,
    ComicDraft,
    Draft,
    DraftGenerateRequest,
    DraftGenerateResponse,
    DraftPatchEngineRequest,
    NeedsInput,
    OutputType,
    Panel,
    PanelRole,
    SingleAdDraft,
)
from backend_core.models.legacy_qa import Answer, Source

GROUNDED_TEXT = "안내문 3조에 따라 먼저 담당 창구에 연락하세요."

FILLED_CATEGORY = "[더미] 생활용품"
FILLED_TARGET = "[더미] 30대 1인 가구"

# ⚠️ Prefixed "[더미]" on purpose. These strings reach a running screen through the fake
# engine, and a plausible-looking one there is how a stub gets mistaken for a measurement
# (AGENTS.md 현재 상태).
_ROLES: tuple[PanelRole, ...] = ("hook", "setup", "problem", "solution", "proof", "cta")


def png_of(width: int, height: int) -> bytes:
    """A PNG header claiming a size, with no pixel data behind it.

    ⚠️ Enough on purpose. Nothing in this app decodes pixels — the bytes go to disk
    untouched — so the only thing a real encoder would add here is time. What the tests need
    is a file whose *header* says a size, because that is what the validator reads.

    The CRC is not computed and nothing checks it, for the same reason.
    """
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + b"\x00\x00\x00\x00"


VALID_PNG = png_of(1024, 768)
"""Comfortably over the 512px short edge that 미결정_대장 N3 fixed."""


def draft_for(output_type: OutputType) -> Draft:
    """A contract-valid draft of the shape the output type demands.

    Six panels for a comic because 0 and 7 are both invalid (INV-1), and `role` follows
    `index` rather than being chosen (INV-5) — a fixture that got either wrong would make
    the pairing checks pass for the wrong reason.
    """
    if output_type == "comic":
        return ComicDraft(
            ad_plan="[더미] 기획안",
            panels=[
                Panel(index=i, role=role, scene=f"[더미] 장면 {i}", dialogue=f"[더미] 대사 {i}")
                for i, role in enumerate(_ROLES, start=1)
            ],
        )
    return SingleAdDraft(ad_plan="[더미] 기획안", copy="[더미] 카피", visual_plan="[더미] 비주얼")


# tests/ -> apps/backend/ -> apps/ -> repo root
CONTRACT_PATH = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "openapi.yaml"


@pytest.fixture(scope="session")
def contract_spec() -> dict[str, Any]:
    """The whole contract document, for tests that compare **paths** rather than schemas.

    Separate from `contract_schemas` because the two ask different questions: schemas police
    our pydantic models, paths police what the app publishes.
    """
    if not CONTRACT_PATH.exists():
        pytest.fail(f"contract not found at {CONTRACT_PATH} — see contract_schemas")
    spec: dict[str, Any] = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    return spec


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


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Cut every test off from the machine's own configuration.

    Startup now creates the schema and seeds the fixed accounts (api.main.lifespan), so
    without this two things happen: the suite writes a real database into the working
    directory, and a developer who has infra/.env exported in their shell runs the tests
    against their own accounts. The second is worse — it passes locally and fails in CI.

    `deps.settings` is an `lru_cache`d singleton read outside the request cycle, so
    `dependency_overrides` cannot reach it; clearing the cache is what makes the patched
    environment take effect.
    """
    for name in [name for name in os.environ if name.startswith("ADGEN_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("ADGEN_DB_PATH", str(tmp_path / "test.sqlite"))

    deps.settings.cache_clear()
    yield
    deps.settings.cache_clear()


class FakeAiEngine:
    """Contract-shaped stand-in for all three seams.

    `available=False` simulates the outage branch (raise); `refuses=True` simulates the
    honest-refusal branch, which each seam expresses differently — `answer: null` on the
    legacy path, an absent `draft` on generation. Both must end where the design says they
    end, which is what the pipeline and session tests check.

    ⚠️ The fake mimics the seams' *shapes*, not the engine's judgement. It never decides
    whether a claim is supported — the guardrail is tested in apps/ai-engine, where it lives,
    and a fake that pretended to run it would make the on/off delta meaningless.
    """

    def __init__(
        self,
        available: bool = True,
        refuses: bool = False,
        needs_input: NeedsInput | None = None,
    ) -> None:
        self.available = available
        self.refuses = refuses
        self.needs_input = needs_input
        self.seen: list[str] = []
        self.drafts_requested: list[DraftGenerateRequest] = []
        self.patches_requested: list[DraftPatchEngineRequest] = []

    def generate(self, question: str, locale: str) -> Answer | None:
        if not self.available:
            raise AiEngineUnavailableError("fake outage")
        self.seen.append(question)
        if self.refuses:
            return None
        return Answer(
            text=GROUNDED_TEXT,
            message_mode="grounded",
            sources=[Source(title="[더미] 공식 안내문", quote="담당 창구에 연락합니다.")],
        )

    def fill_brief(
        self, product_name: str, selling_point: str, note: str, image: bytes, filename: str
    ) -> BriefFillResponse:
        if not self.available:
            raise AiEngineUnavailableError("fake outage")
        if self.needs_input is not None:
            # Inference ran and could not decide: the two values are empty strings, not
            # absent keys, and `needsInput` is what tells the two situations apart.
            return BriefFillResponse(category="", target="", needs_input=self.needs_input)
        return BriefFillResponse(category=FILLED_CATEGORY, target=FILLED_TARGET)

    def generate_draft(self, request: DraftGenerateRequest) -> DraftGenerateResponse:
        if not self.available:
            raise AiEngineUnavailableError("fake outage")
        self.drafts_requested.append(request)
        if self.refuses:
            return DraftGenerateResponse(guardrail_applied=True, refusal_reason="no_evidence")
        return DraftGenerateResponse(draft=draft_for(request.output_type), guardrail_applied=True)

    def patch_draft(self, request: DraftPatchEngineRequest) -> DraftGenerateResponse:
        """Apply the patch the way the real engine is asked to: **only the named parts.**

        ⚠️ The fake actually merges rather than returning a canned draft. A fake that
        returned a fresh draft would pass a test asserting "the copy changed" while hiding
        the failure that matters — the fields *outside* the patch being rewritten, which is
        the whole difference between 부분 교체 and regeneration.
        """
        if not self.available:
            raise AiEngineUnavailableError("fake outage")
        self.patches_requested.append(request)
        if self.refuses:
            return DraftGenerateResponse(guardrail_applied=True, refusal_reason="guardrail")

        changes = request.patch.model_dump(exclude_unset=True, exclude={"panels"})
        patched = request.draft.model_copy(update=changes)
        if request.patch.panels is not None and isinstance(patched, ComicDraft):
            edits = request.patch.panels.root
            patched = patched.model_copy(
                update={
                    "panels": [
                        panel.model_copy(
                            update=edits[str(panel.index)].model_dump(exclude_unset=True)
                        )
                        if str(panel.index) in edits
                        else panel
                        for panel in patched.panels
                    ]
                }
            )
        return DraftGenerateResponse(draft=patched, guardrail_applied=True)


@pytest.fixture
def ai() -> FakeAiEngine:
    return FakeAiEngine()


@pytest.fixture
def client(ai: FakeAiEngine) -> Iterator[TestClient]:
    """App wired to per-test collaborators.

    The real providers are `lru_cache`d singletons, so without these overrides state would
    leak between tests and the first test to run would poison the rest.
    """
    app.dependency_overrides[deps.ai_client] = lambda: ai
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
