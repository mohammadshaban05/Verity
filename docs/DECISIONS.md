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

---

## ADR-008: Offset, passage and chunking conventions

**Date:** 2026-10-30 · **Status:** Accepted (implemented in M1)

**Context.** Every later guarantee (verbatim citations, reproducibility, provenance) depends on passages being exact, addressable slices of a hashed source.

**Decision.**
- **Offsets** are half-open `[start, end)` Python `str` indices (Unicode code points), never bytes. *Note for the future frontend:* JavaScript strings index by UTF-16 code units, so `🔍` has length 1 in Python and 2 in JS. Offsets must be converted at the API boundary.
- **Normalization happens before hashing.** `Document.text` is the canonical snapshot. Any Unicode or whitespace normalization is done by the loader, before the `Document` is constructed. `sha256` is computed over the exact UTF-8 bytes of `text`. Normalizing afterwards would silently invalidate every offset.
- **Models are frozen and reject unknown fields.** A snapshot can't be edited after it is hashed, and typos in stored JSON fail loudly.
- **Documents:** text must be non-empty (empty text means an ingestion bug), `retrieved_at` must be timezone-aware, and `id` is a slug (`[A-Za-z0-9._-]+`) so it can be safely embedded in passage IDs and filenames.
- **Chunking contract:** a hard cap of `len(p.text) <= max_chars`; passages trimmed of surrounding whitespace; every non-whitespace character covered; strictly increasing `start` and `end`; at most `overlap` characters shared between neighbouring passages; split preference paragraph > sentence > whitespace > mid-word; greedy packing.
- **Passage IDs** have the form `<doc_id>@<first 12 hex chars of sha256>:<start>-<end>`, e.g. `nist-ncstar-1a@7c7e5915088e:71-183`. They are deterministic, unique within a document, and readable: you can see the source, version and span. The hash prefix changes when the content changes, so a stored citation can never resolve to a different version of the text. The doc-id character rule excludes `@` and `:`, so IDs parse without ambiguity.

**Algorithm (sliding window with backward snapping), in `src/verity/ingest.py`:**
1. One regex pass over the text records the places where a passage may end. Each is ranked: *paragraph* (a whitespace run with 2+ line breaks, or `\u2029`), *sentence* (after `.`, `!`, `?`, `…`, also when followed by closing quotes or brackets, plus CJK `。！？` with no following space), or *word* (any other whitespace). The same pass records where sentences and words start. The position lists are sorted, so each later lookup is a binary search (`bisect`).
2. For a passage starting at `start`, the window is `[start, start + max_chars]`. It takes the latest paragraph cut in the window if that fills at least half the window. Otherwise it tries the latest sentence cut, then the latest word cut, with the same half-full test. If none of them reaches half full, it takes the latest boundary of any kind. Only when the window has no boundary at all does it cut mid-word.
3. The next passage starts at the earliest *sentence* start within the last `overlap` characters, otherwise the earliest *word* start, otherwise immediately after the previous passage (no overlap). It never starts mid-word.
4. If the overlap start would only see whitespace past the previous end, the overlap is dropped and the chunker skips to the next content. This rules out stalls and infinite loops.

Cost is O(n) to find boundaries plus O(log n) per passage. A 4.8M-character document chunks in under 1 second.

**Tradeoffs.** The hard cap sometimes splits long sentences, which hurts readability. It guarantees that passages fit downstream context and embedding limits. Character counts only approximate token counts, which is fine at this stage. Known limitations:
- **Abbreviations** ("Mr. Smith", "U.S. Army", "a.m. Then") look like sentence ends. This only affects where splits happen, never offsets or correctness. Worth revisiting if retrieval experiments show it matters.
- **Mid-sentence overlap:** when sentences are longer than `overlap`, the overlap region begins at a word inside a sentence.
- **Grapheme clusters** (e.g. a letter plus a combining accent) can still be split at a hard split point.
- **Half-full rule:** the 50% fill threshold is a heuristic and hasn't been tuned. Retrieval experiments (M2, M6) will show whether it should change.

---

## ADR-009: Corpus layout, provenance records and reproducible snapshots

**Date:** 2026-10-30 · **Status:** Accepted (implemented in M1b)

**Context.** Verity has to cite exact spans of sources that are often copyrighted, while keeping research runs reproducible. It also needs to record where each text came from without treating that information as a judgment of credibility.

**Decision.**
- **Commit provenance, not text.** `data/corpus/sources/<id>.json` holds a small provenance record and is committed to git. `data/corpus/raw/<id>.txt` holds the text and is gitignored, alongside the original PDF or HTML kept for auditing. Built snapshots (`data/snapshots/`) are also gitignored.
- **Reproducibility without redistribution.** The record stores `expected_sha256`, the hash of the *normalized* text, taken at first retrieval. Anyone can run `scripts/fetch_corpus.py` and get a yes/no answer on whether their download matches ours. The fetch tools (pypdf, fontTools) are pinned in `uv.lock`, because a different extractor version can produce different text.
- **Provenance fields:**
  - title
  - source name (publisher, agency or outlet)
  - authors
  - source URI (the exact URL the text came from)
  - source type
  - publication date
  - retrieval timestamp (timezone-aware)
  - rights
- **Explicit unknowns.** `published` and `authors` must always be present, written as `null` or `[]` when unknown, so "unknown" is a deliberate statement rather than a forgotten field.
- **No invented precision.** `published` is ISO 8601 at whatever precision is known: `2008`, `2008-11` or `2008-11-20`.
- **Strict schema.** Unknown fields are rejected, so there is nowhere to slip in a credibility score.
- **Source type is metadata, never credibility** (see ADR-006).
- **Loading fails loudly.** Every problem in the corpus is reported at once: a missing record, missing text, bad encoding, a hash mismatch, or duplicate content after normalization. Bad documents are never skipped silently.
- **Snapshot format:**
  - `documents.jsonl` and `passages.jsonl`, in canonical sort order
  - `manifest.json`: format version, Verity version, normalization version, chunking settings, counts, and the sha256 of each data file. It contains no timestamps, so the same input produces byte-identical output.
  - Files are written atomically (temp file, then rename), and the manifest is written last.
  - Loading checks integrity at two levels. File hashes catch any byte change. Semantic checks require every document hash to match its text, and every passage to slice its document exactly and carry its canonical ID.
  - `verify` re-chunks the documents and requires the same passages, which detects changes to the chunker.

**Tradeoffs.** Collaborators have to run the fetch script themselves instead of cloning the texts. A source that changes or disappears online can't be fetched again; the hash shows the drift but can't fix it. Archiving originals (e.g. the Wayback Machine) is a possible follow-up. JSONL is simple and readable, but every load reads the whole snapshot, which is fine at this scale.

---

## ADR-010: Normalization changes encoding only, never content

**Date:** 2026-10-30 · **Status:** Accepted (implemented in M1b)

**Decision.** Version `utf8-nfc-lf-v1`, applied once before hashing (`src/verity/normalize.py`):
1. Strict UTF-8. The byte-order mark is stripped. Any other encoding is rejected, with the byte position of the first invalid byte.
2. NUL bytes are rejected as a sign of a binary or corrupt file.
3. Line endings become `\n`.
4. Control characters are removed, except tab, newline and **form feed**. Form feed is kept because the PDF extractor uses it to mark page breaks, so page numbers can be recovered later for citations.
5. Text is composed to Unicode NFC.

Deliberately *not* done:
- **NFKC.** It turns `x²` into `x2` and changes meaning.
- **Quote straightening, whitespace collapsing, dehyphenation, removing headers and footers.** These change what the source literally says. Where comparisons need to ignore them (e.g. citation matching in M3), they are normalized at comparison time and the stored text stays as it is.

**Tradeoffs.** Stored texts keep PDF extraction artifacts (e.g. `channels.T ypically`, words hyphenated across lines, repeated page headers). That makes them faithful to what the extractor produced, but noisier for retrieval. Any rule change requires a new version string, because it changes every hash.
