# Roadmap

Each milestone produces something runnable with tests, and closes with an entry in [PROGRESS.md](PROGRESS.md). **(U)** = core logic implemented by the project author; **(M)** = scaffolding written by the mentor, plus test specs and reviews.

| # | Milestone | Deliverable | Verification / experiment |
|---|---|---|---|
| 0 | Skeleton **(M)** | uv + Python 3.12, pytest, ruff, docs | Smoke test passes; lint is clean |
| 1 | Data models + chunking **(U)** | `Document` (incl. `source_type`, sha256), `Passage`, `chunk_document()` with exact char offsets | Offset round-trip `doc.text[p.start:p.end] == p.text`; coverage; size/overlap bounds; deterministic IDs; edge cases |
| 2 | BM25 retrieval **(U)** | Your own BM25 behind a `Retriever` protocol | Compare against `rank_bm25`; build a 30–50 claim gold set; Recall@k, MRR |
| 3 | Citation verifier **(U)** | `verify_citation(quote, passage)`: normalization + exact match | Adversarial unit tests: near-misses, cross-passage quotes, paraphrases must fail |
| 4 | LLM judge **(U+M)** | `LLMClient` protocol, `FakeLLM`, Ollama client; structured `Judgment` (SUPPORTS / CONTRADICTS / INSUFFICIENT + quotes), phrased as attribution | Gold-set label accuracy and confusion matrix; quote-validity rate; INSUFFICIENT rate on claims the corpus doesn't address |
| 5 | **End-to-end demo** **(U+M)** | CLI: `claim → BM25 → judge → verifier → Markdown result` on the seed corpus | Run on 10 hand-picked claims (supported, contradicted, not addressed); manual audit of each citation |
| 6 | Dense + hybrid retrieval **(U)** | Sentence embeddings, numpy cosine, Reciprocal Rank Fusion with BM25 | BM25 vs dense vs hybrid on the gold set; error analysis by claim type |
| 7 | Entailment check **(U)** | NLI cross-encoder as a second, non-generative signal | Judge/NLI disagreement rate; hand-inspect the disagreements |
| 8 | Claim decomposition + report | Question → atomic claims → per-claim results → report that keeps attribution and assessment separate (ADR-006) | Sentence-level attribution audit on 10 reports |
| 9 | FastAPI + run logging | API; each run stores corpus hash, model ID, prompt version, outputs | Re-running a logged run reproduces retrieval exactly |
| 10+ | Web retrieval (with snapshots), source independence, contradiction detection, Next.js UI, user-submitted evidence | — | Scoped when reached |

## Corpus plan

Starts with public-domain primary documents: the *9/11 Commission Report* and the NIST WTC investigation reports (NCSTAR 1 / 1A). Later it adds independent reporting, academic research and credible critiques, each tagged with `source_type` and recorded provenance (ADR-006). Every document is downloaded from its original publisher, and its provenance is recorded. No document is added without a verifiable origin.

## External benchmarks (once the basics work)

FEVER, SciFact, AVeriTeC (claim verification with evidence), and ALCE (citation quality in generated text).
