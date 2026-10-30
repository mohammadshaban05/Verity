# Architecture Decision Log

Short records of significant decisions. Each one gives the context, the decision, and the tradeoffs accepted. Superseded decisions stay in the log and are marked as superseded, not deleted.

---

## ADR-001: Deterministic staged pipeline, not an autonomous agent

**Date:** 2026-10-30 · **Status:** Accepted

**Context.** Verity's value depends on being able to measure its reliability. An agent loop, where an LLM decides which tools to call and when to stop, is flexible. It is also hard to reproduce, and a wrong answer can't easily be traced to one step.

**Decision.** Build a pipeline of small, separate stages: corpus → passages → retrieval → judge → citation verifier → report. Each stage is a plain function with typed (Pydantic) inputs and outputs.

**Tradeoffs.** The pipeline is less adaptive. For example, it won't reformulate a query on its own after poor results. In return, each stage can be unit-tested and evaluated on its own, and errors can be traced to a specific stage. Adaptive behavior can be added later as a stage, once there is an evaluation harness to measure whether it helps.

---

## ADR-002: Citations are offset pointers into hashed source snapshots

**Date:** 2026-10-30 · **Status:** Accepted

**Context.** LLMs make up plausible-looking titles, URLs and quotes. A citation that is free text written by a model can't be trusted.

**Decision.** A citation is a pointer `(doc_id, start, end)` into a stored document whose text is fixed by a sha256 hash. The LLM may only reference passage IDs it was given, and it may only quote text from them. A deterministic verifier (no LLM) checks each quote against the stored text before the quote can appear in output. The system, not the model, renders titles and URLs from stored metadata.

**Tradeoffs.** This requires careful offset bookkeeping from ingestion onward, which is why chunking with exact offsets comes first (M1). Quotes must be verbatim (after light normalization), so the system cannot cite a paraphrase directly. That restriction is intended.

---

## ADR-003: Closed, local corpus before any web retrieval

**Date:** 2026-10-30 · **Status:** Accepted

**Context.** Retrieval recall and citation accuracy can't be measured against a corpus that changes, and live web content brings in source drift and prompt-injection risk.

**Decision.** The MVP works only over a fixed local corpus of documents whose provenance is recorded. Web retrieval comes later (M9+), behind the same `Retriever` interface. Fetched pages are snapshotted and hashed.

**Tradeoffs.** Coverage early on is limited to what we curate. Every run can be reproduced, and every error can be investigated.

---

## ADR-004: `typing.Protocol` interfaces; no LLM or RAG frameworks

**Date:** 2026-10-30 · **Status:** Accepted

**Context.** LLM and search providers must be swappable. Frameworks such as LangChain and LlamaIndex make swapping easy, but they hide prompt construction, retrieval scoring and parsing, which are the parts this project needs to understand and evaluate. They also change often.

**Decision.** Define small `Protocol` interfaces (`Retriever`, `LLMClient`). A provider is a class that satisfies the protocol. A scripted `FakeLLM` keeps all tests offline, deterministic and free.

**Tradeoffs.** Some boilerplate gets written by hand (HTTP clients, parsing). We stay in control and the code is easy to read.

---

## ADR-005: Agreement between LLMs is not verification

**Date:** 2026-10-30 · **Status:** Accepted

**Context.** Several LLMs agreeing on a claim looks like corroboration. But the models share training data, biases and failure modes, so their errors are correlated.

**Decision.** Multi-model consensus is never treated as evidence. The signals Verity accepts are, in order of strength: (1) deterministic checks (verbatim quote match, valid IDs), (2) a different model class used as a check (an NLI entailment model, M7), and (3) human-labeled gold data, which is the only ground truth used for evaluation.

**Tradeoffs.** The system will give "INSUFFICIENT" more often than a system that simply accepts consensus. That is the intended behavior.

---

## ADR-006: Attribution verification is separate from claim assessment

**Date:** 2026-10-30 · **Status:** Accepted

**Context.** The corpus will eventually include official documents, independent journalism, academic research and credible critiques. These sources may disagree. Confirming that "Source S states X" is a different question from establishing that "X is true", and mixing the two is a common way systems end up overstating certainty.

**Decision.** Keep two levels apart throughout the system:
- **Attribution verification:** does source S actually say X? Checked by verbatim quote matching and, later, entailment. The judge and verifier produce judgments of the form "Source S states / contradicts / does not address X", never "X is true".
- **Claim assessment:** given several attributed statements, what is the status of X? This weighs source type, independence and quality, and it comes later (M8+).

Each `Document` will carry a `source_type` (`official`, `journalism`, `academic`, `critique`, `other`), starting in M1. Reports present attributed statements ("NIST concluded…", "Critics argue…") separately from any overall assessment.

**Tradeoffs.** Outputs are more verbose and less "headline-like". The system can't quietly turn one authoritative source's claim into a fact.

---

## ADR-007: Tooling: uv, Python 3.12, Pydantic v2, pytest, ruff

**Date:** 2026-10-30 · **Status:** Accepted

**Decision.** `uv` for environments and dependencies (fast, lockfile, manages Python versions). Python is pinned to 3.12 because ML wheels (PyTorch, sentence-transformers) often lag on newer releases. The system Python (3.14) is left untouched. Pydantic v2 for schemas, pytest for tests, ruff for linting and formatting. FastAPI is postponed until there is a working pipeline to serve (M9).

**Tradeoffs.** Python 3.12 means giving up the newest language features in exchange for ML library compatibility.
