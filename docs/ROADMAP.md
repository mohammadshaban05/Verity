# Roadmap

Each milestone produces something runnable with tests, and closes with an entry in [PROGRESS.md](PROGRESS.md). Claude implements each milestone. The project author sets direction, makes design decisions, approves each milestone and evaluates results.

| # | Milestone | Deliverable | Verification / experiment |
|---|---|---|---|
| 0 ✅ | Skeleton | uv + Python 3.12, pytest, ruff, docs | Smoke test passes; lint is clean |
| 1 ✅ | Data models + chunking | `Document` (incl. `source_type`, sha256), `Passage`, `chunk_document()` with exact char offsets | Offset round-trip `doc.text[p.start:p.end] == p.text`; coverage; size/overlap bounds; deterministic IDs; edge cases |
| 1b ✅ | Corpus loader + seed corpus | Provenance records, versioned normalization, `load_corpus`, reproducible JSONL snapshots, fetch script, 4-source WTC corpus | Corrupted, missing-metadata, duplicate and encoding-error tests; byte-identical rebuild; re-fetch reproduces hashes |
| 2 ✅ (awaiting approval) | BM25 retrieval + evaluation | Hand-written BM25 behind a `Retriever` protocol; search-time analyzer with PDF-artifact repair; 44-claim gold set; `search` / `evaluate` CLI | Exact score parity with `rank_bm25`; Recall@1/5/10 and MRR; ablations; artifact study ([report](experiments/m2-bm25.md)) |
| 3 | Citation verifier | `verify_citation(quote, passage)`: normalization + exact match | Adversarial unit tests: near-misses, cross-passage quotes, paraphrases must fail |
| 4 | LLM judge | `LLMClient` protocol, `FakeLLM`, Ollama client; structured `Judgment` (SUPPORTS / CONTRADICTS / INSUFFICIENT + quotes), phrased as attribution | Gold-set label accuracy and confusion matrix; quote-validity rate; INSUFFICIENT rate on claims the corpus doesn't address |
| 5 | **End-to-end demo** | CLI: `claim → BM25 → judge → verifier → Markdown result` on the seed corpus | Run on 10 hand-picked claims (supported, contradicted, not addressed); manual audit of each citation |
| 6 | Dense + hybrid retrieval | Sentence embeddings, numpy cosine, Reciprocal Rank Fusion with BM25 | BM25 vs dense vs hybrid on the gold set; re-pool the gold set with the new system; error analysis by claim type (M2: paraphrase MRR 0.48 vs lexical 0.91) |
| 7 | Entailment check | NLI cross-encoder as a second, non-generative signal | Judge/NLI disagreement rate; hand-inspect the disagreements |
| 8 | Claim decomposition + report | Question → atomic claims → per-claim results → report that keeps attribution and assessment separate (ADR-006) | Sentence-level attribution audit on 10 reports |
| 9 | FastAPI + run logging | API; each run stores corpus hash, model ID, prompt version, outputs | Re-running a logged run reproduces retrieval exactly |
| 10+ | Web retrieval (with snapshots), source independence, contradiction detection, Next.js UI, user-submitted evidence | — | Scoped when reached |

## Corpus plan

**Topic:** the collapse of the World Trade Center buildings on 9/11. The corpus (M1b + M2) contains:
- two official records: 9/11 Commission Report chapter 9, and NIST NCSTAR 1A on WTC 7
- one journalism piece: The Conversation, 2021
- three academic documents:
  - Schneider, IABSE 2019 / arXiv
  - Bažant et al. 2008, authors' preprint (Twin Towers)
  - Hulsey et al. 2020, UAF report funded by AE911Truth (WTC 7)

See [data/corpus/README.md](../data/corpus/README.md).

**Rules:**
- Every document is fetched from its original publisher, with recorded provenance and rights.
- Texts are never committed (ADR-009).
- Source type is metadata, not credibility (ADR-006).

**Rule added in M2:** keep the corpus at its current size unless an experiment needs more. Academic affiliation is not treated as peer review, and funding is recorded rather than scored.

## External benchmarks (once the basics work)

FEVER, SciFact, AVeriTeC (claim verification with evidence), and ALCE (citation quality in generated text).
