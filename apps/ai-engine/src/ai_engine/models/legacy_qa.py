"""Template question-and-answer models — scheduled for deletion.

⚠️ These are **not** part of the ad-generation contract. They belong to the walking
skeleton's placeholder domain (`/v1/generate`) and go away together with that route once
the seam is swapped (API_계약.md 7절, 구간 3). Nothing new should import them.

They are kept for one release so the schema layer can land on a green gate — deleting them
in the same PR that adds the contract models would take the running skeleton down with it.

`RefusalReason` is the one name here that survives: the contract's `DraftGenerateResponse`
uses the same two values. It gets redefined next to the generation schemas rather than
being imported out of this module, so that deleting this file changes nothing real.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Base(BaseModel):
    """camelCase aliases, unknown fields rejected — and `None` still serialized as `null`.

    ⚠️ Deliberately **not** `models.common.Base`. This domain marks a refusal with
    `answer: null` and the contract's base drops null keys, so inheriting it would silently
    turn a refusal into a missing key on a route that is still serving traffic. Legacy code
    keeps legacy semantics until the route itself goes.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


# Why an answer was withheld. `no_evidence` = retrieval came back empty or too weak;
# `guardrail` = text was produced but failed the output-side check.
RefusalReason = Literal["no_evidence", "guardrail"]

Violation = Literal["empty_output", "no_evidence", "unsupported_claim"]


class Passage(Base):
    """One retrieved chunk of source text."""

    id: str
    title: str
    text: str
    tags: list[str] = Field(default_factory=list)
    url: str | None = None
    # Implementation-dependent: only the ordering is part of the contract, never the value.
    score: float = 0.0


class Source(Base):
    """A passage as cited back to the caller."""

    title: str
    quote: str
    url: str | None = None


class GuardrailReport(Base):
    """Result of the output-side check.

    ⚠️ `enabled=False` reports `passed=False` on purpose — a disabled guardrail must not
    read as a clean run, or control-group measurements become indistinguishable from real
    passes.
    """

    enabled: bool
    passed: bool
    violations: list[Violation] = Field(default_factory=list)


class GenerateRequest(Base):
    question: str = Field(min_length=1, max_length=500)
    locale: str = "ko"


class GenerateResponse(Base):
    """`answer: null` is a normal 200.

    ⚠️ The ad-generation contract forbids `null` outright and marks a refusal by *omitting*
    `draft` instead. This module predates that rule and keeps the old shape; do not copy it.
    """

    answer: str | None
    sources: list[Source] = Field(default_factory=list)
    refusal_reason: RefusalReason | None = None
    guardrail_applied: bool = True
