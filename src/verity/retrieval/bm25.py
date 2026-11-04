"""Okapi BM25 over passages, implemented with an inverted index (ADR-011).

For a query q and passage d:

    score(q, d) = sum over terms t in q of
        qtf(t) * idf(t) * tf(t, d) * (k1 + 1) / (tf(t, d) + k1 * (1 - b + b * |d| / avgdl))

- tf saturation (k1): the 10th mention of a term adds much less than the first.
  As tf grows, the term's contribution approaches idf * (k1 + 1).
- length normalization (b): a term mention counts for less in a long passage
  than in a short one. b = 0 turns length normalization off; b = 1 applies it fully.
- idf: rare terms carry more weight than common ones. Two variants:
    "lucene": ln(1 + (N - df + 0.5) / (df + 0.5)), which is always positive (the default)
    "okapi":  ln((N - df + 0.5) / (df + 0.5)), with negative values replaced by
              epsilon * mean idf. This exactly matches rank_bm25's BM25Okapi and is
              used to check this implementation against it.

Ties are broken by passage order (document id, then start offset), so rankings
are fully deterministic.
"""

import math
from collections import Counter
from collections.abc import Sequence
from typing import Literal

from verity.models import Passage
from verity.retrieval.analyze import Analyzer
from verity.retrieval.base import SearchHit

IdfVariant = Literal["lucene", "okapi"]


class BM25Retriever:
    def __init__(
        self,
        passages: Sequence[Passage],
        *,
        analyzer: Analyzer | None = None,
        k1: float = 1.2,
        b: float = 0.75,
        idf: IdfVariant = "lucene",
        epsilon: float = 0.25,
    ) -> None:
        if k1 < 0:
            raise ValueError(f"k1 must be >= 0, got {k1}")
        if not 0 <= b <= 1:
            raise ValueError(f"b must be in [0, 1], got {b}")
        if idf not in ("lucene", "okapi"):
            raise ValueError(f"unknown idf variant {idf!r}")
        self.passages = tuple(passages)
        self.analyzer = analyzer or Analyzer()
        self.k1, self.b = k1, b

        # Inverted index: term -> [(passage index, term frequency)], in passage order.
        self._postings: dict[str, list[tuple[int, int]]] = {}
        self._lengths: list[int] = []
        for index, passage in enumerate(self.passages):
            counts = Counter(self.analyzer(passage.text))
            self._lengths.append(sum(counts.values()))
            for term, tf in counts.items():
                self._postings.setdefault(term, []).append((index, tf))
        n = len(self.passages)
        self._avgdl = sum(self._lengths) / n if n else 0.0
        self._idf = _compute_idf({t: len(p) for t, p in self._postings.items()}, n, idf, epsilon)

    @property
    def vocabulary_size(self) -> int:
        return len(self._postings)

    def idf(self, term: str) -> float:
        return self._idf.get(term, 0.0)

    def search(self, query: str, k: int = 10) -> list[SearchHit]:
        if k < 1:
            raise ValueError(f"k must be >= 1, got {k}")
        # A passage that matches only zero-weight terms is not a match.
        scores = {i: s for i, s in self._score_matching(query).items() if s > 0}
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:k]
        return [
            SearchHit(passage=self.passages[index], score=score, rank=rank)
            for rank, (index, score) in enumerate(ranked, start=1)
        ]

    def scores(self, query: str) -> list[float]:
        """Score of every passage in index order, including zeros (for comparisons)."""
        dense = [0.0] * len(self.passages)
        for index, score in self._score_matching(query).items():
            dense[index] = score
        return dense

    def explain(self, query: str, passage_id: str) -> dict[str, float]:
        """Per-term contribution to one passage's score: why it ranked where it did."""
        index = next(i for i, p in enumerate(self.passages) if p.id == passage_id)
        contributions: dict[str, float] = {}
        for term, qtf in Counter(self.analyzer(query)).items():
            tf = dict(self._postings.get(term, ())).get(index, 0)
            contributions[term] = qtf * self._term_score(term, tf, self._lengths[index])
        return contributions

    def _score_matching(self, query: str) -> dict[int, float]:
        scores: dict[int, float] = {}
        # A repeated query term counts once per occurrence (qtf), as in rank_bm25.
        for term, qtf in Counter(self.analyzer(query)).items():
            for index, tf in self._postings.get(term, ()):
                contribution = qtf * self._term_score(term, tf, self._lengths[index])
                scores[index] = scores.get(index, 0.0) + contribution
        return scores

    def _term_score(self, term: str, tf: int, length: int) -> float:
        if tf == 0:
            return 0.0
        norm = self.k1 * (1 - self.b + self.b * length / self._avgdl)
        return self._idf[term] * tf * (self.k1 + 1) / (tf + norm)


def _compute_idf(
    document_frequency: dict[str, int], n: int, variant: IdfVariant, epsilon: float
) -> dict[str, float]:
    if variant == "lucene":
        return {
            t: math.log(1 + (n - df + 0.5) / (df + 0.5)) for t, df in document_frequency.items()
        }
    idf = {t: math.log(n - df + 0.5) - math.log(df + 0.5) for t, df in document_frequency.items()}
    if not idf:
        return idf
    floor = epsilon * sum(idf.values()) / len(idf)
    return {t: (floor if value < 0 else value) for t, value in idf.items()}
