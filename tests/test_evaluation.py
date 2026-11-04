"""Gold-set validation, evidence resolution, and retrieval metrics."""

import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from factories import make_doc
from verity.corpus import load_corpus
from verity.evaluation import (
    EvaluationError,
    GoldClaim,
    evaluate,
    find_quote,
    lexical_overlap,
    load_gold,
    resolve_evidence,
)
from verity.ingest import chunk_document, passage_id
from verity.models import Passage
from verity.retrieval import SearchHit
from verity.store import build_snapshot

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "eval" / "claims.jsonl"
CORPUS = ROOT / "data" / "corpus"


def claim(label: str = "supported", evidence: list[dict] | None = None, **kw) -> GoldClaim:
    if evidence is None:
        evidence = [{"doc_id": "d", "quote": "fire spread", "stance": "supports"}]
    return GoldClaim(
        id=kw.pop("id", "c1"),
        claim=kw.pop("claim", "Fire spread."),
        label=label,
        topic=kw.pop("topic", "t"),
        origin=kw.pop("origin", "verity"),
        evidence=evidence,
        **kw,
    )


def ev(quote: str, stance: str = "supports", doc_id: str = "d") -> dict:
    return {"doc_id": doc_id, "quote": quote, "stance": stance}


# --- Gold claim validation --------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "stances"),
    [
        ("supported", ["supports", "supports"]),
        ("contradicted", ["contradicts"]),
        ("conflicting", ["supports", "contradicts"]),
        ("insufficient", []),
    ],
)
def test_label_follows_from_evidence_stances(label: str, stances: list[str]) -> None:
    claim(label, [ev(f"quote {i}", s) for i, s in enumerate(stances)])


@pytest.mark.parametrize(
    ("label", "stances"),
    [
        ("supported", ["supports", "contradicts"]),  # really conflicting
        ("contradicted", []),  # absence of evidence is not contradiction
        ("insufficient", ["supports"]),
        ("conflicting", ["supports"]),
    ],
)
def test_label_inconsistent_with_stances_is_rejected(label: str, stances: list[str]) -> None:
    with pytest.raises(ValidationError):
        claim(label, [ev(f"quote {i}", s) for i, s in enumerate(stances)])


def test_empty_quote_is_rejected() -> None:
    with pytest.raises(ValidationError):
        claim("supported", [ev("   ")])


def test_empty_origin_is_rejected_and_dataset_is_its_prefix() -> None:
    with pytest.raises(ValidationError):
        claim(origin=" ")
    assert claim(origin="fever:shared_task_dev:123").dataset == "fever"
    assert claim(origin="verity").dataset == "verity"


# --- Measured phrasing ----------------------------------------------------------------


def test_lexical_overlap_uses_the_closest_quote() -> None:
    c = claim(
        claim="The river floods every spring.",
        evidence=[ev("Snow melts in April."), ev("the river floods each spring")],
    )
    # Claim terms {river, flood, every, spring}; the second quote shares three.
    assert lexical_overlap(c) == pytest.approx(3 / 4)


def test_lexical_overlap_is_undefined_without_evidence() -> None:
    assert lexical_overlap(claim("insufficient", [])) is None


def test_phrasing_is_derived_from_overlap() -> None:
    doc, passages = _doc_and_passages("The river floods each spring. Snow melts in April.", 200)
    claims = [
        claim(id="lex", claim="River floods in spring.", evidence=[ev("The river floods")]),
        claim(id="para", claim="Meltwater arrives late.", evidence=[ev("Snow melts in April.")]),
        claim("insufficient", [], id="none", claim="Bridges."),
    ]
    resolved = resolve_evidence(claims, [doc], passages)
    report = evaluate(ScriptedRetriever(passages, {}), claims, resolved)
    assert [r.phrasing for r in report.results] == ["lexical", "paraphrase", None]


def test_load_gold_reports_line_of_bad_record(tmp_path: Path) -> None:
    good = claim().model_dump_json()
    path = tmp_path / "gold.jsonl"
    path.write_text(good + "\n\n" + '{"id": "x"}\n', encoding="utf-8")
    with pytest.raises(EvaluationError, match="line 3"):
        load_gold(path)


def test_load_gold_rejects_duplicate_ids(tmp_path: Path) -> None:
    path = tmp_path / "gold.jsonl"
    path.write_text(claim().model_dump_json() + "\n" + claim().model_dump_json(), encoding="utf-8")
    with pytest.raises(EvaluationError, match="duplicate"):
        load_gold(path)


# --- Quote location ---------------------------------------------------------------


def test_find_quote_ignores_whitespace_differences_and_finds_every_occurrence() -> None:
    text = "Rain\nfell quickly. Later, rain   fell again."
    assert find_quote(text, "rain fell") == [(26, 37)]  # case-sensitive
    assert find_quote(text, "Rain fell") == [(0, 9)]
    assert find_quote("a b. a b.", "a b.") == [(0, 4), (5, 9)]


def test_find_quote_treats_punctuation_literally() -> None:
    assert find_quote("costs $1.5 (est.)", "$1.5 (est.)") == [(6, 17)]
    assert find_quote("costs 105", "1.5") == []


# --- Evidence resolution --------------------------------------------------------------


def _doc_and_passages(text: str, max_chars: int = 60, overlap: int = 10):
    doc = make_doc(text, doc_id="d")
    return doc, chunk_document(doc, max_chars, overlap)


def test_resolves_quote_to_every_passage_containing_it() -> None:
    doc, passages = _doc_and_passages("Steel beams. Fire spread. Steel beams. Columns failed.", 200)
    resolved = resolve_evidence([claim(evidence=[ev("Fire spread.")])], [doc], passages)
    [item] = resolved["c1"]
    assert item.passage_ids == {passages[0].id}


def test_unknown_document_and_missing_quote_are_reported_together() -> None:
    doc, passages = _doc_and_passages("Fire spread through the floors.")
    claims = [
        claim(id="a", evidence=[ev("Fire spread", doc_id="nope")]),
        claim(id="b", evidence=[ev("volcano")]),
    ]
    with pytest.raises(EvaluationError) as exc:
        resolve_evidence(claims, [doc], passages)
    assert "unknown document 'nope'" in str(exc.value)
    assert "quote not found" in str(exc.value)


def test_quote_spanning_two_passages_is_rejected() -> None:
    text = "First sentence is right here. Second sentence follows it. Third one ends."
    doc = make_doc(text, doc_id="d")
    passages = [
        Passage(id=passage_id(doc, 0, 30), doc_id="d", start=0, end=30, text=text[:30]),
        Passage(id=passage_id(doc, 30, len(text)), doc_id="d", start=30, end=len(text),
                text=text[30:]),
    ]  # fmt: skip
    with pytest.raises(EvaluationError, match="no passage fully contains"):
        resolve_evidence([claim(evidence=[ev("right here. Second")])], [doc], passages)


# --- Metrics ----------------------------------------------------------------------------


class ScriptedRetriever:
    """Returns a fixed ranking for each query, regardless of content."""

    def __init__(self, passages: list[Passage], rankings: dict[str, list[int]]) -> None:
        self.passages, self.rankings = passages, rankings

    def search(self, query: str, k: int = 10) -> list[SearchHit]:
        order = self.rankings.get(query, [])[:k]
        return [
            SearchHit(passage=self.passages[i], score=1.0 / r, rank=r)
            for r, i in enumerate(order, start=1)
        ]


def _metric_fixture():
    sentences = [f"Sentence number {w} is here." for w in ("one", "two", "three", "four", "five")]
    doc = make_doc(" ".join(sentences), doc_id="d")
    passages = chunk_document(doc, 30, 0)
    assert len(passages) == 5
    claims = [
        # Two pieces of evidence, ranked 1 and 7 -> R@1 = R@5 = 0.5, R@10 = 1, RR = 1.
        claim("supported", [ev(sentences[0]), ev(sentences[1])], id="a", claim="qa"),
        # Supporting evidence at rank 2, contradicting at rank 6 (conflicting).
        claim("conflicting", [ev(sentences[2]), ev(sentences[3], "contradicts")],
              id="b", claim="qb"),
        # Evidence never retrieved.
        claim("contradicted", [ev(sentences[4], "contradicts")], id="c", claim="qc"),
        # No evidence: excluded from metrics.
        claim("insufficient", [], id="d", claim="qd"),
    ]  # fmt: skip
    filler = [4, 4, 4, 4, 4]  # padding; only first occurrences matter for our evidence
    rankings = {
        "qa": [0, 2, 3, 4, 4, 4, 1],
        "qb": [0, 2, 0, 0, 0, 3],
        "qc": [0, 1],
        "qd": filler,
    }
    resolved = resolve_evidence(claims, [doc], passages)
    return evaluate(ScriptedRetriever(passages, rankings), claims, resolved)


def test_recall_and_reciprocal_rank_per_claim() -> None:
    report = _metric_fixture()
    a, b, c, d = report.results
    assert (a.recall_at(1), a.recall_at(5), a.recall_at(10), a.reciprocal_rank) == (
        0.5, 0.5, 1.0, 1.0,
    )  # fmt: skip
    assert (b.recall_at(1), b.recall_at(5), b.recall_at(10), b.reciprocal_rank) == (
        0.0, 0.5, 1.0, 0.5,
    )  # fmt: skip
    assert (c.recall_at(10), c.reciprocal_rank) == (0.0, 0.0)
    assert not d.answerable


def test_both_sides_requires_each_stance_in_top_k() -> None:
    b = _metric_fixture().results[1]
    assert not b.both_sides_at(5)
    assert b.both_sides_at(6)


def test_summary_excludes_insufficient_claims_and_averages_over_claims() -> None:
    summary = _metric_fixture().summary
    assert list(summary)[0] == "all"
    assert summary["all"]["n"] == 3
    assert summary["all"]["R@10"] == pytest.approx((1 + 1 + 0) / 3)
    assert summary["all"]["MRR"] == pytest.approx((1 + 0.5 + 0) / 3)
    assert "label=insufficient" not in summary
    assert summary["label=conflicting"]["n"] == 1


# --- The real gold set and committed corpus ----------------------------------------------


def test_gold_set_composition() -> None:
    claims = load_gold(GOLD)
    assert 30 <= len(claims) <= 50
    labels = Counter(c.label for c in claims)
    assert set(labels) == {"supported", "contradicted", "conflicting", "insufficient"}
    assert {"fever", "scifact", "wikicontradict", "verity"} <= {c.dataset for c in claims}
    assert len({c.topic for c in claims}) >= 5  # multi-subject, not one case study
    assert all(json.loads(c.model_dump_json()) for c in claims)


def test_every_gold_quote_resolves_against_the_committed_corpus() -> None:
    # Built from the committed texts, so this runs on a fresh clone without `ingest`.
    snapshot = build_snapshot(load_corpus(CORPUS))
    claims = load_gold(GOLD)
    resolved = resolve_evidence(claims, snapshot.documents, snapshot.passages)
    assert sum(len(items) for items in resolved.values()) == sum(len(c.evidence) for c in claims)
    cross_source = [
        c for c in claims if c.label == "conflicting" and len({e.doc_id for e in c.evidence}) > 1
    ]
    assert cross_source, "expected at least one conflict between different sources"
