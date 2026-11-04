# Roadmap

Each milestone produces something runnable with tests, and closes with an entry in [PROGRESS.md](PROGRESS.md). Claude implements each milestone. The project author sets direction, makes design decisions, approves each milestone and evaluates results.

| # | Milestone | Deliverable | Verification / experiment |
|---|---|---|---|
| 0 ✅ | Skeleton | uv + Python 3.12, pytest, ruff, docs | Smoke test passes; lint is clean |
| 1 ✅ | Data models + chunking | `Document` (incl. `source_type`, sha256), `Passage`, `chunk_document()` with exact char offsets | Offset round-trip `doc.text[p.start:p.end] == p.text`; coverage; size/overlap bounds; deterministic IDs; edge cases |
| 1b ✅ | Corpus loader + seed corpus | Provenance records, versioned normalization, `load_corpus`, reproducible JSONL snapshots, fetch script, first seed corpus (since replaced, see below) | Corrupted, missing-metadata, duplicate and encoding-error tests; byte-identical rebuild; re-fetch reproduces hashes |
| 2 ✅ (awaiting approval) | BM25 retrieval + evaluation | Hand-written BM25 behind a `Retriever` protocol; search-time analyzer; 50-claim gold set on the general-purpose corpus; `search` / `evaluate` CLI | Exact score parity with `rank_bm25`; Recall@1/5/10 and MRR; ablations; artifact study ([report](experiments/m2-bm25.md)) |
| 3 | Citation verifier | `verify_citation(quote, passage)`: normalization + exact match | Adversarial unit tests: near-misses, cross-passage quotes, paraphrases must fail |
| 4 | LLM judge | `LLMClient` protocol, `FakeLLM`, Ollama client; structured `Judgment` (SUPPORTS / CONTRADICTS / INSUFFICIENT + quotes), phrased as attribution | Gold-set label accuracy and confusion matrix; quote-validity rate; INSUFFICIENT rate on claims the corpus doesn't address |
| 5 | **End-to-end demo** | CLI: `claim → BM25 → judge → verifier → Markdown result` on the seed corpus | Run on 10 hand-picked claims (supported, contradicted, not addressed); manual audit of each citation |
| 6 | Dense + hybrid retrieval | Sentence embeddings, numpy cosine, Reciprocal Rank Fusion with BM25 | BM25 vs dense vs hybrid on the gold set; re-pool the gold set with the new system; error analysis by claim type (M2: paraphrase MRR 0.68 vs lexical 0.90) |
| 7 | Entailment check | NLI cross-encoder as a second, non-generative signal | Judge/NLI disagreement rate; hand-inspect the disagreements |
| 8 | Claim decomposition + report | Question → atomic claims → per-claim results → report that keeps attribution and assessment separate (ADR-006) | Sentence-level attribution audit on 10 reports |
| 9 | FastAPI + run logging | API; each run stores corpus hash, model ID, prompt version, outputs | Re-running a logged run reproduces retrieval exactly |
| 10+ | Web retrieval (with snapshots), source independence, contradiction detection, Next.js UI, user-submitted evidence | — | Scoped when reached |

## Corpus plan

Verity is general-purpose, so its development corpus is neutral, multi-subject and redistributable (ADR-013). Specific topics a user mentions are illustrations, not the project's subject.

**Current seed corpus** (97 documents; see [data/corpus/README.md](../data/corpus/README.md)):
- 17 English Wikipedia articles pinned to one revision each: subjects of FEVER claims (history, geology, biology, music, literature, technology, geography, anatomy, astronomy) and articles with contradictions documented by WikiContradict
- 5 Simple English Wikipedia articles as independent second sources
- 75 SciFact abstracts: evidence for a seeded sample of SciFact claims, plus distractors

**Rules:**
- Every document has recorded provenance, rights and a hash; changing sources are pinned to a revision.
- Texts are committed only when their license allows redistribution (ADR-009, ADR-013).
- Source type is metadata, not credibility (ADR-006). Academic affiliation is not treated as peer review, and funding is recorded rather than scored.
- Adapted dataset claims are re-checked against our pinned text; we never copy a label we haven't verified.

**Next additions, when an experiment needs them:**
- more conflicts between sources (currently 2 of 10 conflicting claims)
- a held-out split, for choosing settings without touching the test claims
- long documents (reports, PDFs) under redistributable licenses, so the PDF path is exercised on real data again
- evidence that is reported speech or hypothesis, once the gold-set policy for these is decided

## External benchmarks (once the basics work)

FEVER, SciFact and WikiContradict already feed the seed corpus and gold set, adapted and re-verified. Later: AVeriTeC (real-world claim verification with evidence) and ALCE (citation quality in generated text).
