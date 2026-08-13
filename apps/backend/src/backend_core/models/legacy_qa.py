"""Template question-and-answer models — scheduled for deletion.

⚠️ These are **not** part of the ad-generation contract. They belong to the walking
skeleton's placeholder domain (`/v1/ask` -> `/v1/generate`) and go away together with that
route once the seam is swapped (API_계약.md 7절, 구간 3). Nothing new should import them.

They are kept for one release so the schema layer can land on a green gate — deleting them
in the same PR that adds the contract models would take the running skeleton down with it.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Base(BaseModel):
    """camelCase aliases, unknown fields rejected — and `None` still serialized as `null`.

    ⚠️ Deliberately **not** `models.common.Base`. The contract's base drops null keys, and
    this domain's clients expect `url: null` to be present on a source. Legacy code keeps
    legacy semantics until the route itself goes.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


# grounded          = written by the AI engine from retrieved sources
# official_fallback = pre-approved static text used when the engine refused or is down
#
# ⚠️ Not the contract's MessageMode (`normal` / `degraded`). Same field name on the wire,
# different meaning — which is exactly why this module dies rather than being renamed.
AskMessageMode = Literal["grounded", "official_fallback"]


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
    message_mode: AskMessageMode
    sources: list[Source] = Field(default_factory=list)
