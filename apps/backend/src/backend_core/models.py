"""Wire and domain models.

Field aliases are camelCase because the HTTP contract (packages/contracts/openapi.yaml)
is camelCase while Python code stays snake_case. Keeping the mapping here — instead of
hand-writing dicts in routers — is what stops the two from drifting.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# The frontend branches on these, so they are part of the contract, not free text.
ErrorCode = Literal[
    "INVALID_REQUEST", "NOT_FOUND", "RATE_LIMITED", "UPSTREAM_UNAVAILABLE", "INTERNAL"
]

# grounded        = written by the AI engine from retrieved sources
# official_fallback = pre-approved static text used when the engine refused or is down
MessageMode = Literal["grounded", "official_fallback"]


class Base(BaseModel):
    """camelCase on the wire, snake_case in code, unknown fields rejected.

    ⚠️ `extra="forbid"` is deliberate: a typo'd field that is silently ignored makes the
    caller think it was sent and the server behave as if it never existed.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class Source(Base):
    """One citation backing a generated answer."""

    title: str
    quote: str
    url: str | None = None


class AskRequest(Base):
    """A user question plus whatever profile the answer should be tailored to."""

    question: str = Field(min_length=1, max_length=500)
    locale: str = "ko"


class Answer(Base):
    """Generated answer, or the fallback when nothing could be grounded."""

    text: str
    message_mode: MessageMode
    sources: list[Source] = Field(default_factory=list)


class ErrorBody(Base):
    """Contract error shape — `{code, message}`, not FastAPI's `{"detail": ...}`."""

    code: ErrorCode
    message: str
