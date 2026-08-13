"""Wire models for the ad-generation contract (packages/contracts/openapi.yaml).

`from ai_engine.models import X` always gives a **contract** model. The template
question-and-answer models the walking skeleton still runs on are not re-exported here —
import them from `ai_engine.models.legacy_qa`, which makes every remaining call site
visible and the eventual deletion mechanical.
"""

from ai_engine.models.common import Base, Error, ErrorCode, Omittable, OutputType

__all__ = [
    "Base",
    "Error",
    "ErrorCode",
    "Omittable",
    "OutputType",
]
