"""M2 retrieval experiments: reference comparison, ablations, PDF artifacts, failures.

Usage:
    uv run python scripts/m2_experiments.py [--snapshot DIR] [--gold FILE]

Read-only: loads the snapshot and gold set, prints a plain-text report. The
numbers in docs/experiments/m2-bm25.md come from this script.

The gold set is small (44 claims) and was written by the same people who built
the system, so these results describe this corpus only. Parameter sweeps are
reported for understanding, not for tuning: choosing k1/b on these 37 answerable
claims and then reporting the same numbers would overfit the evaluation.
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
    for doc_id, n in sorted(Counter(p.doc_id for p in passages).items()):
        print(f"  {doc_id:42} {n:4d} passages ({n / len(passages):5.1%})")
    print(f"claims={len(claims)} labels={dict(Counter(c.label for c in claims))}")
    print(f"evidence items={sum(len(c.evidence) for c in claims)}")
    multi = sum(len(r.passage_ids) > 1 for items in resolved.values() for r in items)
    print(f"evidence items contained in >1 passage (chunk overlap): {multi}")

    # ------------------------------------------------------------------------------
    section("2. Baseline: BM25 (lucene idf, k1=1.2, b=0.75, full analyzer)")
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
    for analyzer_name, analyzer in (("raw analyzer", raw), ("full analyzer", Analyzer())):
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
    configs = {
        "raw (casefold + tokenize only)": raw,
        "+ PDF repair": Analyzer(remove_stopwords=False, stem=False),
        "+ PDF repair + stopwords": Analyzer(stem=False),
        "full (repair + stopwords + stem)": Analyzer(),
        "full without PDF repair": Analyzer(repair_pdf_artifacts=False),
        "full without stopwords": Analyzer(remove_stopwords=False),
        "full without stemming": Analyzer(stem=False),
    }
    ablation = {name: run(analyzer=a) for name, a in configs.items()}
    for name, report in ablation.items():
        print(row(name, report))
    print("\nMRR difference vs. full analyzer, paired bootstrap over claims (95% interval):")
    for name, report in ablation.items():
        if report is not ablation["full (repair + stopwords + stem)"]:
            d, lo, hi = paired_bootstrap(ablation["full (repair + stopwords + stem)"], report)
            print(f"  {name:34} {d:+.3f}  [{lo:+.3f}, {hi:+.3f}]")

    # ------------------------------------------------------------------------------
    section("5. PDF extraction artifacts")
    patterns = {
        "kerning split ('T ower')": _KERNING_SPLIT,
        "line-break hyphen ('re-\\nduced')": _LINE_BREAK_HYPHEN,
        "spacing diacritic ('Baˇ zant')": _SPACING_DIACRITIC,
        "ligature (ﬁ ﬂ ﬀ ﬃ ﬄ)": re.compile("[ﬀ-ﬄ]"),
        "page break (\\f)": re.compile("\f"),
        "'intentionally left blank'": re.compile(r"intentionally\s+left\s+blank", re.I),
        "running header ('Final 8-9.5pp')": re.compile(r"Final \d+-\d+\.\d+pp"),
    }
    print(f"{'document':42} " + " ".join(f"{i + 1:>6}" for i in range(len(patterns))))
    for doc in documents:
        counts = [len(p.findall(doc.text)) for p in patterns.values()]
        print(f"{doc.id:42} " + " ".join(f"{n:6d}" for n in counts))
    for i, name in enumerate(patterns, start=1):
        print(f"  {i}: {name}")

    # Figure and table text: axis labels and numbers extracted as a word stream.
    def numeric_share(text: str) -> float:
        tokens = raw(text)
        return sum(t.isdigit() for t in tokens) / max(len(tokens), 1)

    figure_like = {p.id for p in passages if numeric_share(p.text) >= 0.25}
    in_top10 = sum(i in figure_like for r in baseline.results for i in r.ranked_ids[:10])
    print("\npassages where >= 25% of tokens are numbers (figures, tables, TOC, references):")
    for doc_id, n in sorted(Counter(by_id[i].doc_id for i in figure_like).items()):
        print(f"  {doc_id:42} {n:4d}")
    print(f"  share of all top-10 results that are such passages: "
          f"{in_top10 / sum(len(r.ranked_ids[:10]) for r in baseline.results):.1%} "
          f"(corpus share {len(figure_like) / len(passages):.1%})")  # fmt: skip

    print("\nMost frequent kerning-split joins (check they are real words):")
    joins: Counter[tuple[str, str]] = Counter()
    for doc in documents:
        for m in _KERNING_SPLIT.finditer(doc.text):
            joined = Analyzer()(m.group(0))
            joins[(m.group(0), " ".join(joined))] += 1
    for (span, terms), n in joins.most_common(25):
        print(f"  {n:4d}  {span!r:22} -> {terms}")

    print("\nRepair ablation by evidence document (full analyzer with vs. without repair):")
    full = ablation["full (repair + stopwords + stem)"]
    norepair = ablation["full without PDF repair"]
    by_doc: dict[str, list[tuple[float, float]]] = {}
    for a, b in zip(full.answerable, norepair.answerable, strict=True):
        for item, ra, rb in zip(resolved[a.claim.id], a.evidence_ranks, b.evidence_ranks,
                                strict=True):  # fmt: skip
            rr = [1 / r if r else 0.0 for r in (ra, rb)]
            by_doc.setdefault(item.evidence.doc_id, []).append((rr[0], rr[1]))
    for doc_id, pairs in sorted(by_doc.items()):
        with_repair, without = mean(p[0] for p in pairs), mean(p[1] for p in pairs)
        print(f"  {doc_id:42} n={len(pairs):2d}  mean 1/rank with repair {with_repair:.3f}  "
              f"without {without:.3f}")  # fmt: skip
    print("\nClaims whose first-relevant rank changed with repair:")
    for a, b in zip(full.answerable, norepair.answerable, strict=True):
        ra, rb = _first(a.evidence_ranks), _first(b.evidence_ranks)
        if ra != rb:
            print(f"  {a.claim.id:9} with repair {ra!s:>5}  without {rb!s:>5}  {a.claim.claim}")

    # ------------------------------------------------------------------------------
    section("6. Parameter sensitivity (reported, NOT used for tuning)")
    ks, bs = (0.5, 0.9, 1.2, 1.5, 2.0), (0.0, 0.25, 0.5, 0.75, 1.0)
    print("MRR, rows k1, columns b")
    print("      " + " ".join(f"{b:6.2f}" for b in bs))
    for k1 in ks:
        cells = [metrics(run(k1=k1, b=b).answerable)["MRR"] for b in bs]
        print(f"{k1:5.1f} " + " ".join(f"{c:6.3f}" for c in cells))

    # ------------------------------------------------------------------------------
    section("7. Long-document effects and document share of the top 10")
    lengths = Counter()
    for p in passages:
        lengths[p.doc_id] += len(index.analyzer(p.text))
    for doc_id in sorted(lengths):
        n = sum(p.doc_id == doc_id for p in passages)
        print(f"  {doc_id:42} mean passage length {lengths[doc_id] / n:6.1f} terms")
    share = Counter(by_id[i].doc_id for r in baseline.results for i in r.ranked_ids[:10])
    total = sum(share.values())
    corpus_share = Counter(p.doc_id for p in passages)
    print(f"\n{'document':42} {'top-10 share':>12} {'corpus share':>12}")
    for doc_id in sorted(corpus_share):
        print(f"  {doc_id:40} {share[doc_id] / total:12.1%} "
              f"{corpus_share[doc_id] / len(passages):12.1%}")  # fmt: skip

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
    section("8. Topic confusion: WTC 7 vs. Twin Towers")
    wtc7_docs = {"hulsey-2020-uaf-wtc7"}
    tt_docs = {"bazant-2008-wtc-twin-towers", "conversation-2021-twin-towers-collapse"}
    for topic, wrong in (("wtc7", tt_docs), ("twin_towers", wtc7_docs)):
        rs = [r for r in baseline.results if r.claim.topic == topic]
        top5 = [by_id[i].doc_id for r in rs for i in r.ranked_ids[:5]]
        off = sum(d in wrong for d in top5)
        print(f"{topic:12} claims={len(rs):2d}: {off}/{len(top5)} top-5 hits come from "
              f"documents about the other topic ({sorted(wrong)})")  # fmt: skip
    print("(NIST NCSTAR 1A, the Commission chapter and Schneider are not topic-pure.)")

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
            print(f"  {r.claim.id:9} top score {r.top_score or 0:6.2f} ({top})  {r.claim.claim}")

    # ------------------------------------------------------------------------------
    section("10. Successes and failures (baseline)")
    ok = sorted((r for r in baseline.answerable), key=lambda r: -r.reciprocal_rank)
    print("Best (relevant passage at rank 1):")
    for r in [r for r in ok if r.reciprocal_rank == 1][:6]:
        print(f"  {r.claim.id:9} [{r.claim.phrasing}] {r.claim.claim}")
    print("\nFailures (no relevant passage in top 10):")
    for r in baseline.answerable:
        if r.recall_at(10) == 0:
            _explain_failure(index, r, resolved, by_id)


def _top_indices(scores: Sequence[float], k: int) -> list[int]:
    return sorted(range(len(scores)), key=lambda i: (-scores[i], i))[:k]


def _first(ranks: Sequence[int | None]) -> int | None:
    found = [r for r in ranks if r is not None]
    return min(found) if found else None


def _explain_failure(index, result, resolved, by_id) -> None:
    claim = result.claim
    first = _first(result.evidence_ranks)
    print(f"\n  {claim.id} [{claim.label}/{claim.phrasing}] {claim.claim}")
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
