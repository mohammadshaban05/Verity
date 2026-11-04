"""The retrieval interface shared by every search backend (ADR-004)."""

from dataclasses import dataclass
from typing import Protocol

from verity.models import Passage


@dataclass(frozen=True)
class SearchHit:
    passage: Passage
    score: float
    rank: int  # 1-based


class Retriever(Protocol):
    def search(self, query: str, k: int = 10) -> list[SearchHit]:
        """Return up to ``k`` passages, best first. Passages that match no query
        term are never returned, even when fewer than ``k`` passages match."""
        ...
