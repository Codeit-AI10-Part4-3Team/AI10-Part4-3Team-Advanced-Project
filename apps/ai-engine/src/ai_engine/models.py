"""Contract and pipeline models.

camelCase on the wire (packages/contracts/openapi.yaml), snake_case in code.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# Why an answer was withheld. `no_evidence` = retrieval came back empty or too weak;
# `guardrail` = text was produced but failed the output-side check.
RefusalReason = Literal["no_evidence", "guardrail"]

Violation = Literal["empty_output", "no_evidence", "unsupported_claim"]


class Base(BaseModel):
    """camelCase aliases, unknown fields rejected (a typo must not pass silently)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


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

    Omitting the key instead of nulling it would make "refused" and "response missing"
    indistinguishable for the caller.
    """

    answer: str | None
    sources: list[Source] = Field(default_factory=list)
    refusal_reason: RefusalReason | None = None
    guardrail_applied: bool = True
