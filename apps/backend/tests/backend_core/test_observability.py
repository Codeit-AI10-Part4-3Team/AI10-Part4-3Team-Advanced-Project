"""What the 08-26 report reads has to survive being read.

⚠️ These tests are about the **record**, not about the metrics. p95 and a failure rate are
arithmetic; the parts that break silently are the ones below - a line shape that drifts away
from the aggregation script, a handler installed twice, and a log that a full disk turns into
an outage.
"""

import logging
from pathlib import Path

import pytest

from backend_core import observability


def test_a_measurement_line_carries_the_prefix_first(caplog: pytest.LogCaptureFixture) -> None:
    """The aggregation script selects on `PREFIX` at the start of the message.

    ⚠️ Asserting the *shape*, not just the values. `ai_engine.usage` made the same promise
    and for the same reason: a format change makes past logs and present logs uncountable
    together, and nobody notices until the report is due.
    """
    logger = logging.getLogger("test.obs")
    with caplog.at_level(logging.INFO, logger="test.obs"):
        observability.record(logger, "image:render", "done", 118_432, job="job-1")

    assert caplog.messages == ["obs seam=image:render outcome=done elapsed_ms=118432 job=job-1"]


def test_extra_fields_keep_the_key_value_shape(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.obs")
    with caplog.at_level(logging.INFO, logger="test.obs"):
        observability.record(logger, "brief:fill", "degraded", 8)

    assert caplog.messages == ["obs seam=brief:fill outcome=degraded elapsed_ms=8"]


def test_elapsed_is_readable_before_the_block_ends() -> None:
    """A seam reports inside its own branch, so the timer must be readable mid-flight.

    ⚠️ If this only worked on exit, every failure path would have to duplicate the record
    call after the `with` - and the paths that raise (`generation_timeout`) could not record
    at all.
    """
    with observability.measured() as elapsed_ms:
        first = elapsed_ms()
        second = elapsed_ms()

    assert isinstance(first, int)
    assert second >= first >= 0


def test_installing_twice_leaves_one_handler(tmp_path: Path) -> None:
    """⚠️ Otherwise every test in this suite would add another, and the last tests would
    write each line dozens of times - into files nobody reads, at a cost nobody attributes.

    ⚠️ The count is taken **after the first install**, not before it. Any test that started
    the app has already been through `lifespan`, which installs one and never removes it — so
    a baseline read before this call is only zero when this file runs alone, and the suite
    caught exactly that (2026-08-21).
    """
    root = logging.getLogger()

    observability.install_file_log(tmp_path / "logs", retention_d=30)
    after_first = len(root.handlers)
    observability.install_file_log(tmp_path / "logs", retention_d=30)

    try:
        ours = [h for h in root.handlers if getattr(h, "_adgen_tag", None) is not None]
        assert len(ours) == 1
        assert len(root.handlers) == after_first
    finally:
        for handler in [h for h in root.handlers if getattr(h, "_adgen_tag", None) is not None]:
            root.removeHandler(handler)
            handler.close()


def test_a_measurement_reaches_the_file(tmp_path: Path) -> None:
    """The point of the file is that it outlives the container. Prove something lands in it."""
    observability.install_file_log(tmp_path / "logs", retention_d=30)
    try:
        observability.record(logging.getLogger("test.obs"), "draft:generate", "ok", 4200)
    finally:
        for handler in [
            h for h in logging.getLogger().handlers if getattr(h, "_adgen_tag", None) is not None
        ]:
            handler.flush()
            logging.getLogger().removeHandler(handler)
            handler.close()

    written = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
    assert "obs seam=draft:generate outcome=ok elapsed_ms=4200" in written


def test_an_unusable_log_directory_does_not_stop_the_service(tmp_path: Path) -> None:
    """⚠️ A full or read-only volume must not take the deployment down with it.

    Losing the measurement costs a number in a report. Raising here costs the service: this
    runs inside `lifespan`, so the exception would abort startup and the stack would answer
    nothing at all.
    """
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("", encoding="utf-8")

    observability.install_file_log(blocker / "logs", retention_d=30)

    assert not any(getattr(h, "_adgen_tag", None) is not None for h in logging.getLogger().handlers)
