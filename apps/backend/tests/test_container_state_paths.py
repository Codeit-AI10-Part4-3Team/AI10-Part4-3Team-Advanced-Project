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

WRITABLE_SETTINGS = ["db_path", "image_dir"]
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
