"""Runtime settings.

Values come from the environment (infra/.env, never committed). The defaults are the
offline ones so a fresh clone runs without configuration.
"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

GenerationMode = Literal["stub", "model"]
"""Which side of every generation seam is live.

⚠️ **This is the single switch, and it is deliberately visible.** 구현_범위 1.1절 requires
that the running branch be readable without opening the source, because mistaking a stub
response for a measurement is the failure that quietly invalidates every number we report.
`stub` is the default while the walking skeleton is being assembled; flipping to `model`
turns the not-yet-written branches into explicit failures rather than silent fallbacks.
"""


class Settings(BaseSettings):
    """`ADGEN_` prefix keeps our variables distinguishable from everything else on the host."""

    model_config = SettingsConfigDict(env_prefix="ADGEN_", extra="ignore")

    generation_mode: GenerationMode = "stub"

    # Where the stub places its placeholder marker. Kept configurable so a screenshot in a
    # report can never be mistaken for a real render.
    stub_marker: str = "STUB"


def get_settings() -> Settings:
    """Read settings. Callers cache — see `ai_engine.service`, which holds the instance."""
    return Settings()
