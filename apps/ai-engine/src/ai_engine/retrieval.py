"""Retrieval stage: source corpus -> grounded passages.

What this is: the *shape* of retrieval — a scored lookup behind a `Retriever` protocol —
running on a committed dummy fixture so the whole vertical slice works offline.
What this is not: a real retriever. Chroma/pgvector + an embedding model replaces
`FixtureRetriever`; the protocol is the seam that makes that a one-line change at the
call site.

⚠️ Pipeline direction is one-way — this module must not import `generation`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Protocol

from ai_engine.models.legacy_qa import Passage

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "corpus.jsonl"

_NON_WORD = re.compile(r"[^0-9A-Za-z가-힣]")


class Retriever(Protocol):
    """Seam between the dummy fixture and the real vector index."""

    def search(self, query: str, *, top_k: int) -> list[Passage]: ...


def _bigrams(text: str) -> set[str]:
    """Character bigrams — a whitespace tokenizer is useless for Korean agglutination.

    Deliberately crude: a stand-in for embedding similarity, kept dependency-free so CI
    never drags in the RAG stack (heavy deps live in the `rag` extra).
    """
    compact = _NON_WORD.sub("", text)
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


class FixtureRetriever:
    """Lexical retriever over the committed dummy corpus.

    ⚠️ Known limitation, and the reason embeddings are on the critical path: lexical
    matching misses paraphrase, so a question worded differently from the corpus retrieves
    nothing and the engine refuses. Refusing is the *safe* failure — but it is a recall
    failure, not correct behaviour.
    """

    # A passage must earn some lexical overlap to be considered evidence at all. Without
    # a floor, an unrelated question still "matches" something and the engine answers from
    # evidence that has nothing to do with it.
    MIN_OVERLAP = 0.08

    def __init__(self, passages: list[Passage]) -> None:
        self._passages = passages

    @classmethod
    def from_jsonl(cls, path: Path = FIXTURE_PATH) -> FixtureRetriever:
        """Load the corpus fixture.

        Raises FileNotFoundError rather than falling back to an empty corpus: an engine
        that silently retrieves nothing looks like "no evidence" and quietly degrades
        every answer to the caller's fallback.
        """
        with path.open(encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        return cls([Passage(**row) for row in rows])

    @property
    def passages(self) -> list[Passage]:
        """Read-only view of the loaded corpus, for tests and eval tooling."""
        return list(self._passages)

    def search(self, query: str, *, top_k: int = 3) -> list[Passage]:
        query_grams = _bigrams(query)
        if not query_grams:
            return []

        scored: list[Passage] = []
        for passage in self._passages:
            overlap = len(query_grams & _bigrams(passage.text)) / len(query_grams)
            if overlap < self.MIN_OVERLAP:
                continue
            scored.append(passage.model_copy(update={"score": round(overlap, 4)}))

        # id is the tie-breaker so repeated runs (and therefore scoring) are stable.
        scored.sort(key=lambda p: (-p.score, p.id))
        return scored[:top_k]
