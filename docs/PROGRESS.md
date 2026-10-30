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

### M1b: Corpus loader + seed corpus (2026-10-30)

- `src/verity/normalize.py`: versioned normalization (`utf8-nfc-lf-v1`) applied before hashing (ADR-010)
- `src/verity/models.py`: new `Provenance` model with source name, authors, partial-precision publication date and rights; `Document` now inherits it
- `src/verity/corpus.py`: `load_corpus()` plus the `SourceRecord` schema; reports every problem at once (ADR-009)
- `src/verity/store.py`: `build_snapshot`, `save_snapshot`, `load_snapshot`, `check_reproducible`
- `python -m verity ingest | verify` (`src/verity/__main__.py`)
- `scripts/fetch_corpus.py`: downloads, extracts and hashes sources; reports drift on re-fetch
- **Seed corpus:** the collapse of the World Trade Center buildings on 9/11. 4 documents, 413,015 characters, 575 passages at the agreed settings (1000 / 200 / 0.5 / strict overlap cap)

  | id | type | published | rights |
  |---|---|---|---|
  | `911-commission-ch9` | official | 2004-07-22 | public domain (U.S.) |
  | `nist-ncstar-1a` | official | 2008-11 | U.S. government work |
  | `conversation-2021-twin-towers-collapse` | journalism | 2021-09-08 | CC BY-ND 4.0 |
  | `schneider-2019-wtc-structural-dynamics` | academic | 2019-10-25 | arXiv non-exclusive license |

- **Reproducibility checks on the real corpus:**
  - re-downloading all 4 sources from scratch reproduced every recorded hash
  - two independent builds produced byte-identical snapshot files
  - `verify` re-chunks the documents and gets identical passages
- **Tests:** 158 passing
  - 16 normalization tests, including a Hypothesis idempotence test
  - 32 corpus tests covering corrupted documents, missing metadata, duplicates, encoding errors and multi-problem reporting
  - 20 store tests covering round trip, byte-identical rebuilds, and corruption caught both by file hashes and by semantic checks
  - 2 CLI tests and 4 HTML-extractor tests
  - model tests grew from 36 to 52 with the new provenance rules

## Current limitations

- **PDF extraction artifacts stay in the stored text:** kerning splits (`channels.T ypically`), words hyphenated across lines (272 in Commission chapter 9), and repeated page headers (12× "This page intentionally left blank." in NCSTAR 1A). This is deliberate (ADR-010), but it adds noise for BM25. A different extractor is worth evaluating.
- **Corpus balance:**
  - The only academic source (Schneider 2019) argues *against* the "too weak to arrest the collapse" view, and there is no mainstream peer-reviewed engineering paper (e.g. Bažant et al. 2008), because none was available under an open license.
  - There is no critique source yet. The UAF WTC 7 report is only hosted by an advocacy group.
  - The Commission chapter covers the emergency response more than the collapse mechanics.
- **Page numbers** can be recovered from form-feed markers but aren't exposed yet.
- **HTML extraction** relies on site-specific rules (`itemprop="articleBody"`, labelled lists, "Read more:"), tested only on The Conversation.
- **No archival copy:** if a source changes or disappears online, its drift can be detected but it can't be re-fetched.
- **From M1:** abbreviation splitting, mid-sentence overlap starts, untuned chunking defaults.
- No evaluation data yet.

## Next steps (awaiting approval)

**Decisions for the project author**
1. Which mainstream peer-reviewed paper to add (it can be supplied locally through university library access).
2. Whether to add a critique source, and which one.

**M2: BM25 retrieval**
- A `Retriever` protocol and a BM25 implementation
- A comparison against `rank_bm25`
- A hand-labeled gold set of 30–50 claims over this corpus, scored with Recall@k and MRR
