"""Wire models for the ad-generation contract (packages/contracts/openapi.yaml).

`from backend_core.models import X` always gives a **contract** model. The template
question-and-answer models that the walking skeleton still runs on are not re-exported
here — import them from `backend_core.models.legacy_qa`, which makes every remaining call
site visible and the eventual deletion mechanical.
"""

from backend_core.models.auth import LoginRequest, Me
from backend_core.models.common import (
    Base,
    Error,
    ErrorCode,
    MessageMode,
    Omittable,
    OutputType,
)

__all__ = [
    "Base",
    "Error",
    "ErrorCode",
    "LoginRequest",
    "Me",
    "MessageMode",
    "Omittable",
    "OutputType",
]
