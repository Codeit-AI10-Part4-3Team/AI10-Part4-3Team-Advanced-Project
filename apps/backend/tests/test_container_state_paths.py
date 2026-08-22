"""Every writable path the app uses must be configured to live under the volume.

⚠️ This file exists because the CI smoke test cannot see this class of bug and the unit
suite cannot either. The smoke test starts the image and asks `/health`, which touches no
state; the unit suite points every path at `tmp_path`. In between sits the real failure:
a path whose default resolves under `/app` — root-owned, with the app running as `appuser`
— and it surfaces the first time a **person** does the thing that writes there.

We hit it twice on 2026-08-14. `ADGEN_DB_PATH` failed at startup, which was loud and CI
caught it. `ADGEN_IMAGE_DIR` would have failed at the first photo upload, which is quiet:
`/health` stays green, the smoke test passes, and the deployment looks fine until someone
uses it.

So this checks the **Dockerfile as text**, not a running container. It is not a substitute
for a container test; it is the cheapest thing that fails when someone adds a fourth
writable path and configures it in only one of the two places.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend_core.config import Settings

# tests/ -> apps/backend/
DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"
COMPOSE = Path(__file__).resolve().parents[3] / "infra" / "docker-compose.yml"

WRITABLE_SETTINGS = ["db_path", "image_dir", "log_dir"]
"""Settings naming somewhere the app writes. Add to this when a new one appears — that is
the whole point of the list."""


def _env_names(field_names: list[str]) -> list[str]:
    return [f"ADGEN_{name.upper()}" for name in field_names]


def test_every_writable_default_is_relative_and_therefore_unusable_in_the_image() -> None:
    """The premise of the two tests below, stated so it cannot quietly stop being true.

    The code defaults are relative on purpose — they are for running `uvicorn` from
    apps/backend. Relative is exactly what makes them wrong inside the image, where the
    working directory is root-owned.
    """
    # ⚠️ The declared defaults, not `Settings()`. The autouse fixture in conftest points
    # every path at `tmp_path`, so an instance here would report absolute paths and this
    # test would fail for a reason that has nothing to do with what it checks.
    for name in WRITABLE_SETTINGS:
        value = str(Settings.model_fields[name].default)
        assert not Path(value).is_absolute(), (
            f"{name} default is absolute; if it now points at the volume this test's premise "
            "is gone and the two below are checking nothing"
        )


@pytest.mark.parametrize("variable", _env_names(WRITABLE_SETTINGS))
def test_the_image_overrides_every_writable_path(variable: str) -> None:
    """⚠️ The Dockerfile, not compose, is the place this has to be right.

    compose also sets both, but `docker run` does not read compose — and the image has to
    start on its own. The Dockerfile is also where `/data` is created and handed to
    `appuser`, so the ownership and the default belong in one file.
    """
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(rf"^\s*(ENV\s+)?{variable}=/data/", dockerfile, re.MULTILINE), (
        f"{variable} is not pointed at /data in apps/backend/Dockerfile. Its default is a "
        "relative path, which resolves under the root-owned WORKDIR and fails with "
        "PermissionError — at startup for the database, at the first upload for images."
    )


@pytest.mark.parametrize("variable", _env_names(WRITABLE_SETTINGS))
def test_compose_also_names_every_writable_path(variable: str) -> None:
    """So an operator has one file to change all of them in, and so the two cannot diverge
    without this failing."""
    assert variable in COMPOSE.read_text(encoding="utf-8"), (
        f"{variable} is missing from infra/docker-compose.yml"
    )


NOT_OPERATOR_FACING = {
    # Set to a service name by compose itself, not by an operator — putting it in .env would
    # invite someone to point the backend at a host that does not exist inside the network.
    "ai_engine_url",
}
"""Settings deliberately absent from the operator's knobs. Add here **with a reason**."""


def test_every_setting_reaches_the_container() -> None:
    """⚠️ `infra/docker-compose.yml` has no `env_file:`, so a variable it does not name
    **does not exist in the container** — whatever `infra/.env` says.

    That is not a theoretical gap. `ADGEN_ART_STYLES` was added to `.env.example` and not to
    compose, which quietly defeated the decision it exists for: the art-style candidates are
    kept out of the source because 미결정_대장 A절 3번 is 차단, so configuration is the *only*
    way in — and in the only deployment we have there was no way in at all
    (2026-08-14, PR #87 리뷰에서 신호정 발견).

    Every new setting now has to be routed or explicitly excused. Forgetting is what this
    catches; disagreeing is what `NOT_OPERATOR_FACING` is for.
    """
    compose = COMPOSE.read_text(encoding="utf-8")

    missing = sorted(
        f"ADGEN_{name.upper()}"
        for name in Settings.model_fields
        if name not in NOT_OPERATOR_FACING and f"ADGEN_{name.upper()}" not in compose
    )

    assert missing == [], (
        f"{missing} exist in Settings but are not passed through infra/docker-compose.yml. "
        "Add them there, or add them to NOT_OPERATOR_FACING with a reason."
    )
