"""Metric functions — pure, so they can be re-run on any prediction set.

Rule: `(prediction, truth) -> score`. No I/O, no model calls, no globals. That is what
makes a reported number reproducible by someone who only has this file and the goldens.

⚠️ Naming matters here. This directory is collected by pytest (`testpaths = ["tests",
"eval"]`), so anything named `test_*.py` runs in CI. The actual scoring run — which calls
a model and costs money — must be named `run_*.py` instead.
"""

from __future__ import annotations

import re

_NON_WORD = re.compile(r"[^0-9A-Za-z가-힣]")


def _bigrams(text: str) -> set[str]:
    compact = _NON_WORD.sub("", text)
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


def source_fidelity(prediction: str, sources: list[str]) -> float:
    """Share of the prediction's bigrams that appear in its cited sources.

    A crude, deterministic stand-in for "did the answer stay inside its evidence". Pair it
    with a cross-model LLM grading pass — and use a grading model *different* from the
    generation model, or the score measures self-agreement rather than fidelity.
    """
    predicted = _bigrams(prediction)
    if not predicted:
        return 0.0
    allowed: set[str] = set()
    for source in sources:
        allowed |= _bigrams(source)
    return round(len(predicted & allowed) / len(predicted), 4)


def hallucination_rate(reports: list[bool]) -> float:
    """Share of outputs that failed verification. `reports[i] = passed?`"""
    if not reports:
        return 0.0
    return round(sum(1 for passed in reports if not passed) / len(reports), 4)


def suppression_rate(guardrail_off: list[bool], guardrail_on: list[bool]) -> float:
    """Relative reduction in hallucination when the guardrail is on.

    This is the headline number of a guardrail claim, so it is defined here once rather
    than recomputed in a notebook: `(off - on) / off`. Returns 0.0 when the control run
    hallucinated nothing — there was nothing to suppress, and reporting 100% would be a lie.
    """
    off = hallucination_rate(guardrail_off)
    if off == 0.0:
        return 0.0
    on = hallucination_rate(guardrail_on)
    return round(max(0.0, (off - on) / off), 4)


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile — p95 latency without pulling in numpy.

    Used for end-to-end latency reporting, where the mean alone hides the tail that
    actually breaks the user experience.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), round(p / 100 * len(ordered) + 0.5)))
    return ordered[rank - 1]
