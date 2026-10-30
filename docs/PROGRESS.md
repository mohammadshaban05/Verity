# Progress Log

## Completed milestones

### M0: Project skeleton (2026-10-30)

- uv-managed environment with Python 3.12 pinned (`.python-version`, `requires-python`)
- `src/` layout package `verity`, built with hatchling
- pytest configured; one smoke test checks that the package imports
- ruff configured for lint and format (rules E, F, I, B, UP; line length 100)
- Decision log (`DECISIONS.md`, ADR-001 to ADR-007) and roadmap (`ROADMAP.md`)

### M1: Data models + chunking (2026-10-30)

- `src/verity/models.py`
  - `sha256_hex` (UTF-8, no normalization) and a `SourceType` enum
  - `Document`: frozen; validates id format, non-empty fields, a timezone-aware timestamp and that the hash matches the text on every load
  - `Passage`: frozen; validates its span
- `src/verity/ingest.py`: `chunk_document()` (sliding window with backward snapping to paragraph, sentence or word boundaries; algorithm in ADR-008)
- Passage ID format: `<doc_id>@<sha256[:12]>:<start>-<end>`
- Tests:
  - 68 passing. Models: 36. Chunker: 31, including a Hypothesis property test over 300 random documents. Smoke: 1.
  - Extra one-off checks (not in the suite): 20,000 random documents with every invariant holding, and a 4.8M-character document chunked in under 1 s.
  - Mutation check: deliberately disabling each designed behavior (half-full rule, closing quotes, CJK, sentence-start overlap, hash in ID, whitespace-gap restart) makes its test fail.
- ADR-008 accepted
- Workflow changed: Claude implements; the project author directs, decides and evaluates

## Current limitations

- Sentence detection is a heuristic: abbreviations ("Mr.", "U.S.", "a.m.") are treated as sentence ends.
- The overlap can begin mid-sentence when sentences are longer than `overlap`.
- Grapheme clusters can be split at hard cut points (rare: only when a window has no whitespace).
- Character counts approximate tokens; the defaults (1000/200) haven't been tuned.
- No loader yet: Documents are built in code. No corpus downloaded. No evaluation data.

## Next steps (awaiting approval)

**M1b: corpus loader**
- Read `.txt`/`.md` files plus a provenance sidecar (title, source URI, source type, retrieval date)
- Apply explicit text normalization (NFC, line endings) *before* hashing
- Persist Documents and Passages as JSONL
- Add one seed document from an official source

**M2: BM25 retrieval**
- A `Retriever` protocol and a BM25 implementation
- A comparison against `rank_bm25`
- A hand-labeled gold set of 30–50 claims, with Recall@k and MRR
