"""Contract commons — what every other schema module in this package builds on.

Contract: packages/contracts/openapi.yaml. Four rules from its header shape this module:

1. camelCase on the wire, snake_case in code  -> `Base.model_config` alias generator
2. lowercase snake_case enum values           -> the `Literal`s below
3. unknown fields rejected                    -> `extra="forbid"`
4. **no `null` anywhere**                     -> `Omittable` + `Base._omit_absent`

Only the fourth needs work. pydantic treats `X | None` as "accepts null", but the contract
says absence is a missing key and emptiness is `""` — a `null` on the wire is a 422 in
either direction. The two halves of that rule live here so no schema module can forget one.

⚠️ These definitions are deliberately duplicated in apps/ai-engine. The two apps must not
import each other (AGENTS.md), so drift is caught by the contract-conformance tests rather
than by sharing code.
"""

from typing import Annotated, Literal, TypeVar

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    SerializerFunctionWrapHandler,
    model_serializer,
)
from pydantic.alias_generators import to_camel

T = TypeVar("T")


def _reject_null(value: object) -> object:
    """Reject an explicit `null` before pydantic can accept it as `None`.

    Without this, `Omittable[str]` would happily take `{"note": null}` — and the caller
    that meant "clear this field" would silently get "field not present" instead. The two
    are different requests in this contract (API_계약.md 3절).
    """
    if value is None:
        raise ValueError('null is not allowed by the contract; omit the key or send ""')
    return value


# A field the contract allows to be absent. Absent means "not applicable to this output
# type" or "not there yet" — never null. Use `""` for "present but empty".
Omittable = Annotated[T | None, BeforeValidator(_reject_null)]


class Base(BaseModel):
    """Wire model base: camelCase aliases, unknown fields rejected, `None` never emitted.

    `extra="forbid"` is deliberate: a typo'd field that is silently ignored makes the
    caller believe it was sent and the server behave as if it never existed.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: SerializerFunctionWrapHandler):
        """Drop absent fields instead of serializing them as `null`.

        Done here rather than per-route `response_model_exclude_none` because that flag is
        opt-in per endpoint: one route added without it puts `null` on the wire, and the
        rule is only worth having if it holds everywhere.

        ⚠️ **Do not annotate the return type.** pydantic builds the *serialization* JSON
        schema from a model serializer's return annotation, so `-> dict[str, Any]` replaces
        every model's response schema with a bare `{"type": "object",
        "additionalProperties": true}`. FastAPI then publishes that in `/openapi.json` and
        the contract disappears from the generated spec — silently, because the wire bytes
        stay correct. Left unannotated, pydantic keeps the real schema.
        `test_serialization_schema_survives_the_serializer` locks this down.
        """
        return {key: value for key, value in handler(self).items() if value is not None}


ErrorCode = Literal[
    "INVALID_REQUEST",
    "NOT_FOUND",
    "UNAUTHORIZED",
    "INVALID_CREDENTIALS",
    "DUPLICATE_ACCOUNT",
    "NOT_IMPLEMENTED",
    "RATE_LIMITED",
    "UPSTREAM_UNAVAILABLE",
    "INTERNAL",
    "INSUFFICIENT_INPUT",
    "INVALID_IMAGE",
    "CONTENT_POLICY_REJECTED",
    "GENERATION_TIMEOUT",
    "REVISION_CONFLICT",
    "STATE_CONFLICT",
]
"""All 15 codes in the contract. Clients branch on these, so they are the contract itself.

`DUPLICATE_ACCOUNT` and `RATE_LIMITED` have no emit site in the first cut (signup is 501,
rate limiting is out of scope). They stay because renaming a code later means rewriting the
screens that branch on it.
"""


class Error(Base):
    """`{code, message}` — not FastAPI's default `{"detail": ...}`.

    `message` is developer-facing for now; user-facing wording is a deployment-stage
    concern (기획서 17.2).
    """

    code: ErrorCode
    message: str


OutputType = Literal["comic", "single_ad"]
"""Fixed when the session is created. Changing it means a new session, not an update."""


MessageMode = Literal["normal", "degraded"]
"""`degraded` = `brief:fill` was skipped and the user's own input was used instead.

Once a session is `degraded` it stays `degraded` for the rest of its life. The value is a
reported metric alongside the guardrail control run, so losing it invalidates the
measurement (ADR-0005).
"""
