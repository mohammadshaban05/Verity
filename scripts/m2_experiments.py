"""M2 retrieval experiments: reference comparison, ablations, artifacts, failures.

Usage:
    uv run python scripts/m2_experiments.py [--snapshot DIR] [--gold FILE]

Read-only: loads the snapshot and gold set, prints a plain-text report. The
numbers in docs/experiments/m2-bm25.md come from this script.

The gold set is small (a few dozen claims), so these results describe this
corpus only. Parameter sweeps are reported for understanding, not for tuning:
choosing k1/b on the same answerable claims and then reporting the resulting
numbers would overfit the evaluation.
"""

import argparse
import random
import re
import time
from collections import Counter
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path
from statistics import mean

from rank_bm25 import BM25Okapi

from verity.evaluation import (
    EvaluationReport,
    evaluate,
    format_summary,
    load_gold,
    metrics,
    resolve_evidence,
)
from verity.retrieval import Analyzer, BM25Retriever
from verity.retrieval.analyze import _KERNING_SPLIT, _LINE_BREAK_HYPHEN, _SPACING_DIACRITIC
from verity.store import load_snapshot


def source_group(doc_id: str) -> str:
    """Corpus collection a document belongs to: "wiki", "simplewiki" or "scifact"."""
    return doc_id.split("-", 1)[0]


def section(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def row(name: str, report: EvaluationReport) -> str:
    m = metrics(report.answerable)
    return f"{name:34} {m['R@1']:6.3f} {m['R@5']:6.3f} {m['R@10']:6.3f} {m['MRR']:6.3f}"


HEADER = f"{'configuration':34} {'R@1':>6} {'R@5':>6} {'R@10':>6} {'MRR':>6}"


def paired_bootstrap(
    a: EvaluationReport, b: EvaluationReport, samples: int = 10_000, seed: int = 0
) -> tuple[float, float, float]:
    """MRR(b) - MRR(a) with a 95% bootstrap interval, resampling claims (paired)."""
    ra = [r.reciprocal_rank for r in a.answerable]
    rb = [r.reciprocal_rank for r in b.answerable]
    rng = random.Random(seed)
    n = len(ra)
    diffs = sorted(
        mean(rb[i] - ra[i] for i in (rng.randrange(n) for _ in range(n))) for _ in range(samples)
    )
    return mean(rb) - mean(ra), diffs[int(0.025 * samples)], diffs[int(0.975 * samples)]


def auroc(positives: Sequence[float], negatives: Sequence[float]) -> float:
    """Probability that a random positive outscores a random negative (ties count 1/2)."""
    wins = sum((p > n) + 0.5 * (p == n) for p in positives for n in negatives)
    return wins / (len(positives) * len(negatives))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=Path("data/snapshots/current"))
    parser.add_argument("--gold", type=Path, default=Path("data/eval/claims.jsonl"))
    args = parser.parse_args()

    snapshot = load_snapshot(args.snapshot)
    passages, documents = snapshot.passages, snapshot.documents
    claims = load_gold(args.gold)
    resolved = resolve_evidence(claims, documents, passages)
    by_id = {p.id: p for p in passages}

    def run(**kwargs) -> EvaluationReport:
        return evaluate(BM25Retriever(passages, **kwargs), claims, resolved)

    # ------------------------------------------------------------------------------
    section("1. Corpus and gold set")
    print(f"documents={len(documents)} passages={len(passages)}")
    docs_per_group = Counter(source_group(d.id) for d in documents)
    passages_per_group = Counter(source_group(p.doc_id) for p in passages)
    for group, n in sorted(passages_per_group.items()):
        print(f"  {group:12} {docs_per_group[group]:3d} documents {n:5d} passages "
              f"({n / len(passages):5.1%})")  # fmt: skip
    largest = Counter(p.doc_id for p in passages).most_common(5)
    print("  largest documents: " + ", ".join(f"{d} ({n})" for d, n in largest))
    print(f"claims={len(claims)} labels={dict(Counter(c.label for c in claims))}")
    print(f"datasets={dict(Counter(c.dataset for c in claims))}")
    print(f"topics={dict(Counter(c.topic for c in claims))}")
    print(f"evidence items={sum(len(c.evidence) for c in claims)}")
    multi = sum(len(r.passage_ids) > 1 for items in resolved.values() for r in items)
    print(f"evidence items contained in >1 passage (chunk overlap): {multi}")

    # ------------------------------------------------------------------------------
    section("2. Baseline: BM25 (lucene idf, k1=1.2, b=0.75, default analyzer)")
    t0 = time.perf_counter()
    index = BM25Retriever(passages)
    build = time.perf_counter() - t0
    t0 = time.perf_counter()
    baseline = evaluate(index, claims, resolved)
    query_time = (time.perf_counter() - t0) / len(claims)
    print(f"index build {build * 1000:.0f} ms, vocabulary {index.vocabulary_size} terms, "
          f"{query_time * 1000:.1f} ms/query")  # fmt: skip
    print(format_summary(baseline.summary))
    conflicting = [r for r in baseline.results if r.claim.label == "conflicting"]
    for k in (5, 10, 20):
        both = sum(r.both_sides_at(k) for r in conflicting)
        print(f"conflicting claims with both sides in top {k}: {both}/{len(conflicting)}")

    # ------------------------------------------------------------------------------
    section("3. Reference comparison with rank_bm25 (BM25Okapi)")
    raw = Analyzer(repair_pdf_artifacts=False, remove_stopwords=False, stem=False)
    for analyzer_name, analyzer in (("raw analyzer", raw), ("default analyzer", Analyzer())):
        ours = BM25Retriever(passages, analyzer=analyzer, k1=1.5, b=0.75, idf="okapi")
        ref = BM25Okapi([analyzer(p.text) for p in passages], k1=1.5, b=0.75, epsilon=0.25)
        max_diff, top10_same = 0.0, 0
        for c in claims:
            a = ours.scores(c.claim)
            r = list(ref.get_scores(analyzer(c.claim)))
            max_diff = max(max_diff, max(abs(x - y) for x, y in zip(a, r, strict=True)))
            # rank_bm25 has no tie-break rule; compare with ours on (score, index).
            ref_top = sorted(range(len(r)), key=lambda i: (-r[i], i))[:10]
            top10_same += ref_top == _top_indices(a, 10)
        print(f"{analyzer_name}: max |score diff| over {len(claims)} queries x "
              f"{len(passages)} passages = {max_diff:.2e}; identical top-10: "
              f"{top10_same}/{len(claims)}")  # fmt: skip
    print()
    print(HEADER)
    print(row("ours, lucene idf k1=1.2 (default)", baseline))
    print(row("ours, okapi idf k1=1.5 (=rank_bm25)", run(k1=1.5, idf="okapi")))
    print(row("ours, okapi idf k1=1.2", run(idf="okapi")))
    d, lo, hi = paired_bootstrap(baseline, run(k1=1.5, idf="okapi"))
    print(f"MRR(rank_bm25 settings) - MRR(default) = {d:+.3f} [{lo:+.3f}, {hi:+.3f}]")
    df = Counter(t for p in passages for t in set(index.analyzer(p.text)))
    common = sorted((t for t, n in df.items() if n > len(passages) / 2), key=lambda t: -df[t])
    print(f"terms in more than half the passages (okapi idf < 0, floored): {common}")

    # ------------------------------------------------------------------------------
    section("4. Analyzer ablations")
    print(HEADER)
    default_name = "default (stopwords + stem)"
    configs = {
        "raw (casefold + tokenize only)": raw,
        "+ stopwords": Analyzer(stem=False),
        default_name: Analyzer(),
        "default + PDF repair": Analyzer(repair_pdf_artifacts=True),
        "default without stopwords": Analyzer(remove_stopwords=False),
        "default without stemming": Analyzer(stem=False),
    }
    ablation = {name: run(analyzer=a) for name, a in configs.items()}
    for name, report in ablation.items():
        print(row(name, report))
    print("\nMRR difference vs. default analyzer, paired bootstrap over claims (95% interval):")
    for name, report in ablation.items():
        if name != default_name:
            d, lo, hi = paired_bootstrap(ablation[default_name], report)
            print(f"  {name:34} {d:+.3f}  [{lo:+.3f}, {hi:+.3f}]")

    # ------------------------------------------------------------------------------
    section("5. Extraction artifacts and the PDF repair rules")
    patterns = {
        "kerning split ('T able')": _KERNING_SPLIT,
        "line-break hyphen ('re-\\nduced')": _LINE_BREAK_HYPHEN,
        "spacing diacritic ('Dvoˇ rák')": _SPACING_DIACRITIC,
        "ligature (ﬁ ﬂ ﬀ ﬃ ﬄ)": re.compile("[ﬀ-ﬄ]"),
        "page break (\\f)": re.compile("\f"),
    }
    print(f"{'pattern':36} {'matches':>8} {'documents':>10}")
    for name, pattern in patterns.items():
        counts = [len(pattern.findall(doc.text)) for doc in documents]
        print(f"{name:36} {sum(counts):8d} {sum(n > 0 for n in counts):10d}")

    print("\nMost frequent kerning-rule matches (would be joined if repair were on):")
    joins: Counter[tuple[str, str]] = Counter()
    for doc in documents:
        for m in _KERNING_SPLIT.finditer(doc.text):
            joined = Analyzer(repair_pdf_artifacts=True)(m.group(0))
            joins[(m.group(0), " ".join(joined))] += 1
    for (span, terms), n in joins.most_common(15):
        print(f"  {n:4d}  {span!r:22} -> {terms}")

    # Figure and table text: numbers extracted as a word stream.
    def numeric_share(text: str) -> float:
        tokens = raw(text)
        return sum(t.isdigit() for t in tokens) / max(len(tokens), 1)

    figure_like = {p.id for p in passages if numeric_share(p.text) >= 0.25}
    in_top10 = sum(i in figure_like for r in baseline.results for i in r.ranked_ids[:10])
    print(f"\npassages where >= 25% of tokens are numbers: {len(figure_like)} "
          f"({dict(Counter(source_group(by_id[i].doc_id) for i in figure_like))})")  # fmt: skip
    print(f"  share of all top-10 results that are such passages: "
          f"{in_top10 / sum(len(r.ranked_ids[:10]) for r in baseline.results):.1%} "
          f"(corpus share {len(figure_like) / len(passages):.1%})")  # fmt: skip

    print("\nClaims whose first-relevant rank changes when PDF repair is turned on:")
    repaired = ablation["default + PDF repair"]
    changed = 0
    for a, b in zip(baseline.answerable, repaired.answerable, strict=True):
        ra, rb = _first(a.evidence_ranks), _first(b.evidence_ranks)
        if ra != rb:
            changed += 1
            print(f"  {a.claim.id:10} default {ra!s:>5}  with repair {rb!s:>5}  {a.claim.claim}")
    if not changed:
        print("  none")

    # ------------------------------------------------------------------------------
    section("6. Parameter sensitivity (reported, NOT used for tuning)")
    ks, bs = (0.5, 0.9, 1.2, 1.5, 2.0), (0.0, 0.25, 0.5, 0.75, 1.0)
    print("MRR, rows k1, columns b")
    print("      " + " ".join(f"{b:6.2f}" for b in bs))
    for k1 in ks:
        cells = [metrics(run(k1=k1, b=b).answerable)["MRR"] for b in bs]
        print(f"{k1:5.1f} " + " ".join(f"{c:6.3f}" for c in cells))

    # ------------------------------------------------------------------------------
    section("7. Long-document effects and source share of the top 10")
    terms_per_group: dict[str, list[int]] = {}
    for p in passages:
        terms_per_group.setdefault(source_group(p.doc_id), []).append(len(index.analyzer(p.text)))
    for group, lengths in sorted(terms_per_group.items()):
        print(f"  {group:12} mean passage length {mean(lengths):6.1f} terms")
    share = Counter(
        source_group(by_id[i].doc_id) for r in baseline.results for i in r.ranked_ids[:10]
    )
    total = sum(share.values())
    print(f"\n  {'source':12} {'top-10 share':>12} {'corpus share':>12}")
    for group in sorted(passages_per_group):
        print(f"  {group:12} {share[group] / total:12.1%} "
              f"{passages_per_group[group] / len(passages):12.1%}")  # fmt: skip
    doc_share = Counter(by_id[i].doc_id for r in baseline.results for i in r.ranked_ids[:10])
    print("  documents with the largest top-10 share: "
          + ", ".join(f"{d} {n / total:.1%}" for d, n in doc_share.most_common(5)))  # fmt: skip

    redundant = 0
    for r in baseline.results:
        top = [by_id[i] for i in r.ranked_ids[:10]]
        redundant += sum(
            1
            for x, y in pairwise(top)
            if x.doc_id == y.doc_id and min(x.end, y.end) > max(x.start, y.start)
        )
    print(f"\nadjacent overlapping passage pairs in top 10 (chunk overlap): {redundant} "
          f"across {len(claims)} queries")  # fmt: skip

    # ------------------------------------------------------------------------------
    section("8. Source confusion: where do the top-5 hits come from?")
    print("Share of top-5 hits from a document that holds evidence for the claim,")
    print("and from the other collection (encyclopedia vs. abstracts):")
    for dataset in sorted({r.claim.dataset for r in baseline.answerable}):
        rs = [r for r in baseline.answerable if r.claim.dataset == dataset]
        top5 = [(r, by_id[i].doc_id) for r in rs for i in r.ranked_ids[:5]]
        own = sum(d in {e.doc_id for e in r.claim.evidence} for r, d in top5)
        other = sum(
            (source_group(d) == "scifact")
            != all(source_group(e.doc_id) == "scifact" for e in r.claim.evidence)
            for r, d in top5
        )
        print(f"  {dataset:15} claims={len(rs):2d}  evidence documents {own / len(top5):5.1%}  "
              f"other collection {other / len(top5):5.1%}")  # fmt: skip

    print("\nCross-source claims (evidence in more than one document):")
    for r in baseline.answerable:
        if len({e.doc_id for e in r.claim.evidence}) > 1:
            parts = [
                f"{item.evidence.doc_id}/{item.evidence.stance[:4]}@{rank}"
                for item, rank in zip(resolved[r.claim.id], r.evidence_ranks, strict=True)
            ]
            print(f"  {r.claim.id:10} [{r.claim.label}] " + ", ".join(parts))

    # ------------------------------------------------------------------------------
    section("9. Can the top-1 score detect 'insufficient' claims?")
    pos = [r.top_score or 0.0 for r in baseline.results if r.answerable]
    neg = [r.top_score or 0.0 for r in baseline.results if not r.answerable]
    print(f"answerable top-1 score: mean {mean(pos):.2f}, min {min(pos):.2f}")
    print(f"insufficient top-1 score: mean {mean(neg):.2f}, max {max(neg):.2f}")
    print(f"AUROC (answerable > insufficient) = {auroc(pos, neg):.3f}")
    for r in baseline.results:
        if not r.answerable:
            top = by_id[r.ranked_ids[0]].doc_id if r.ranked_ids else "-"
            print(f"  {r.claim.id:10} top score {r.top_score or 0:6.2f} ({top})  {r.claim.claim}")

    # ------------------------------------------------------------------------------
    section("10. Successes and failures (baseline)")
    ok = sorted((r for r in baseline.answerable), key=lambda r: -r.reciprocal_rank)
    print("Best (relevant passage at rank 1):")
    for r in [r for r in ok if r.reciprocal_rank == 1][:6]:
        print(f"  {r.claim.id:10} [{r.phrasing}] {r.claim.claim}")
    print("\nFailures (no relevant passage in top 10):")
    failures = [r for r in baseline.answerable if r.recall_at(10) == 0]
    for r in failures:
        _explain_failure(index, r, resolved, by_id)
    if not failures:
        print("  none")
    print("\nSlowest claims (first relevant passage below rank 3):")
    for r in sorted(baseline.answerable, key=lambda r: r.reciprocal_rank):
        if r.reciprocal_rank < 1 / 3:
            _explain_failure(index, r, resolved, by_id)


def _top_indices(scores: Sequence[float], k: int) -> list[int]:
    return sorted(range(len(scores)), key=lambda i: (-scores[i], i))[:k]


def _first(ranks: Sequence[int | None]) -> int | None:
    found = [r for r in ranks if r is not None]
    return min(found) if found else None


def _explain_failure(index, result, resolved, by_id) -> None:
    claim = result.claim
    first = _first(result.evidence_ranks)
    print(f"\n  {claim.id} [{claim.label}/{result.phrasing}] {claim.claim}")
    print(f"    first relevant rank: {first}")
    query_terms = index.analyzer(claim.claim)
    print(f"    query terms: {query_terms}")
    top = by_id[result.ranked_ids[0]]
    top_contrib = {t: round(s, 2) for t, s in index.explain(claim.claim, top.id).items() if s}
    print(f"    rank 1: {top.doc_id} score {result.top_score:.2f} {top_contrib}")
    print(f"      {_snippet(top.text)}")
    item = resolved[claim.id][0]
    pid = sorted(item.passage_ids)[0]
    contrib = {t: round(s, 2) for t, s in index.explain(claim.claim, pid).items() if s}
    print(f"    evidence passage: score {sum(contrib.values()):.2f} {contrib}")
    print(f"      quote: {_snippet(item.evidence.quote)}")
    missing = [t for t in query_terms if t not in contrib]
    print(f"    query terms absent from the evidence passage: {missing}")


def _snippet(text: str, n: int = 140) -> str:
    flat = " ".join(text.split())
    return flat[:n] + ("..." if len(flat) > n else "")


if __name__ == "__main__":
    main()
