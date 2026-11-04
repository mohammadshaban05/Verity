"""Retrieval evaluation against a hand-labeled gold set (ADR-012).

Gold labels describe what passages *say*, not which explanation is correct.
Each claim lists evidence quotes copied verbatim from the snapshot, each with a
stance: the quote supports or contradicts the claim. The claim's label follows
from those stances:

    supported     every evidence quote supports the claim
    contradicted  every evidence quote contradicts the claim
    conflicting   the corpus contains quotes on both sides
    insufficient  the corpus does not address the claim (no evidence)

Relevance is defined by the evidence text, not by passage IDs. A quote is
located in its document (whitespace-insensitive, every occurrence), and a
passage is relevant if it contains a full occurrence. The gold set therefore
stays valid if chunking changes.

Metrics are computed over answerable claims (those with evidence):
    Recall@k  share of a claim's evidence quotes found in the top k (a quote counts
              as found if any passage containing it is in the top k), averaged over claims
    MRR       mean of 1 / rank of the first relevant passage (0 if none was returned)
"""

import json
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from verity.models import Document, Passage
from verity.retrieval.base import Retriever

Label = Literal["supported", "contradicted", "conflicting", "insufficient"]
Stance = Literal["supports", "contradicts"]
CUTOFFS = (1, 5, 10)


class EvaluationError(ValueError):
    pass


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str
    quote: str
    stance: Stance


class GoldClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    claim: str
    label: Label
    topic: str
    phrasing: Literal["lexical", "paraphrase"]
    evidence: tuple[Evidence, ...]
    note: str = ""

    @model_validator(mode="after")
    def _label_matches_evidence(self) -> Self:
        stances = {e.stance for e in self.evidence}
        expected: Label
        if not stances:
            expected = "insufficient"
        elif stances == {"supports"}:
            expected = "supported"
        elif stances == {"contradicts"}:
            expected = "contradicted"
        else:
            expected = "conflicting"
        if self.label != expected:
            raise ValueError(f"label {self.label!r} but evidence stances imply {expected!r}")
        if not self.claim.strip() or any(not e.quote.strip() for e in self.evidence):
            raise ValueError("claim and quotes must not be empty")
        return self


def load_gold(path: Path) -> list[GoldClaim]:
    claims: list[GoldClaim] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            claims.append(GoldClaim.model_validate(json.loads(line)))
        except (ValidationError, json.JSONDecodeError) as exc:
            raise EvaluationError(f"{path} line {line_no}: {exc}") from exc
    ids = [c.id for c in claims]
    if len(ids) != len(set(ids)):
        raise EvaluationError(f"{path}: duplicate claim ids")
    return claims


def find_quote(text: str, quote: str) -> list[tuple[int, int]]:
    """Every occurrence of ``quote`` in ``text``, allowing any whitespace between
    words (PDF line breaks are not content). Returns (start, end) offsets."""
    pattern = r"\s+".join(re.escape(word) for word in quote.split())
    return [(m.start(), m.end()) for m in re.finditer(pattern, text)]


@dataclass(frozen=True)
class ResolvedEvidence:
    evidence: Evidence
    spans: tuple[tuple[int, int], ...]
    passage_ids: frozenset[str]


def resolve_evidence(
    claims: Sequence[GoldClaim], documents: Sequence[Document], passages: Sequence[Passage]
) -> dict[str, list[ResolvedEvidence]]:
    """Map each claim's quotes to the passages that fully contain them. Raises
    EvaluationError if a quote is not in its document or no passage contains it."""
    docs = {d.id: d for d in documents}
    by_doc: dict[str, list[Passage]] = defaultdict(list)
    for p in passages:
        by_doc[p.doc_id].append(p)

    resolved: dict[str, list[ResolvedEvidence]] = {}
    problems: list[str] = []
    for claim in claims:
        items = []
        for ev in claim.evidence:
            if ev.doc_id not in docs:
                problems.append(f"{claim.id}: unknown document {ev.doc_id!r}")
                continue
            spans = find_quote(docs[ev.doc_id].text, ev.quote)
            if not spans:
                problems.append(f"{claim.id}: quote not found in {ev.doc_id}: {ev.quote[:60]!r}")
                continue
            ids = frozenset(
                p.id for p in by_doc[ev.doc_id] for s, e in spans if p.start <= s and e <= p.end
            )
            if not ids:
                problems.append(f"{claim.id}: no passage fully contains quote {ev.quote[:60]!r}")
                continue
            items.append(ResolvedEvidence(ev, tuple(spans), ids))
        resolved[claim.id] = items
    if problems:
        raise EvaluationError("gold set does not match the snapshot:\n  " + "\n  ".join(problems))
    return resolved


@dataclass(frozen=True)
class ClaimResult:
    claim: GoldClaim
    ranked_ids: tuple[str, ...]  # retrieved passage ids, best first
    top_score: float | None
    evidence_ranks: tuple[int | None, ...]  # best rank of each evidence quote
    stances: tuple[Stance, ...]

    @property
    def answerable(self) -> bool:
        return bool(self.claim.evidence)

    def recall_at(self, k: int) -> float:
        return mean(r is not None and r <= k for r in self.evidence_ranks)

    @property
    def reciprocal_rank(self) -> float:
        found = [r for r in self.evidence_ranks if r is not None]
        return 1 / min(found) if found else 0.0

    def both_sides_at(self, k: int) -> bool:
        """For conflicting claims: are supporting AND contradicting quotes in the top k?"""
        return all(
            any(
                r is not None and r <= k
                for r, s in zip(self.evidence_ranks, self.stances, strict=True)
                if s == side
            )
            for side in ("supports", "contradicts")
        )


@dataclass
class EvaluationReport:
    results: list[ClaimResult]
    summary: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def answerable(self) -> list[ClaimResult]:
        return [r for r in self.results if r.answerable]


def evaluate(
    retriever: Retriever,
    claims: Sequence[GoldClaim],
    resolved: dict[str, list[ResolvedEvidence]],
    depth: int = 1000,
) -> EvaluationReport:
    results = []
    for claim in claims:
        hits = retriever.search(claim.claim, k=depth)
        rank_of = {h.passage.id: h.rank for h in hits}
        ranks = tuple(
            min((rank_of[i] for i in item.passage_ids if i in rank_of), default=None)
            for item in resolved[claim.id]
        )
        results.append(
            ClaimResult(
                claim=claim,
                ranked_ids=tuple(h.passage.id for h in hits),
                top_score=hits[0].score if hits else None,
                evidence_ranks=ranks,
                stances=tuple(item.evidence.stance for item in resolved[claim.id]),
            )
        )
    report = EvaluationReport(results)
    report.summary = summarize(report.answerable)
    return report


def summarize(results: Sequence[ClaimResult]) -> dict[str, dict[str, float]]:
    """Metrics overall and by label, topic and phrasing (answerable claims only)."""
    groups: dict[str, list[ClaimResult]] = {}
    for r in results:
        for key in (
            f"label={r.claim.label}",
            f"topic={r.claim.topic}",
            f"phrasing={r.claim.phrasing}",
        ):
            groups.setdefault(key, []).append(r)
    ordered = {"all": list(results)} | dict(sorted(groups.items()))
    return {name: metrics(group) for name, group in ordered.items()}


def metrics(results: Sequence[ClaimResult]) -> dict[str, float]:
    if not results:
        return {}
    out: dict[str, float] = {"n": len(results)}
    for k in CUTOFFS:
        out[f"R@{k}"] = mean(r.recall_at(k) for r in results)
    out["MRR"] = mean(r.reciprocal_rank for r in results)
    return out


def format_summary(summary: dict[str, dict[str, float]]) -> str:
    header = (
        f"{'group':28} {'n':>3} " + " ".join(f"{f'R@{k}':>6}" for k in CUTOFFS) + f" {'MRR':>6}"
    )
    lines = [header, "-" * len(header)]
    for name, m in summary.items():
        if not m:
            continue
        cells = " ".join(f"{m[f'R@{k}']:6.3f}" for k in CUTOFFS)
        lines.append(f"{name:28} {int(m['n']):3d} {cells} {m['MRR']:6.3f}")
    return "\n".join(lines)
