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

### M2: BM25 retrieval + evaluation (2026-10-30, awaiting approval)

- **Sources (user decisions 1–5):**
  - `bazant-2008-wtc-twin-towers`: the authors' preprint of the *J. Eng. Mech.* 2008 paper, from Bažant's Northwestern page
  - `hulsey-2020-uaf-wtc7`: the final UAF report, linked from ine.uaf.edu/wtc7
  - Both are local only. The corpus is now 6 documents and 909 passages.
- **Provenance:** new required fields `affiliations`, `publication_status` and `disclosures`, filled in for all 6 records. Academic affiliation is not treated as peer review, and funding is recorded, never scored (ADR-009, data/corpus/README.md).
- **`src/verity/retrieval/`:**
  - `Retriever` protocol and `SearchHit`
  - `Analyzer`: search-time PDF-artifact repair, NFKC, folding, stopwords, S-stemmer (ADR-011)
  - `BM25Retriever`: hand-written inverted index, Lucene and Okapi idf, `explain()`
- **`src/verity/evaluation.py`:** gold-set schema in which the label must follow from the evidence stances; quote → passage resolution; Recall@k, MRR, and a both-sides check (ADR-012)
- **Gold set** `data/eval/claims.jsonl`:
  - 44 claims: 22 supported, 10 contradicted, 5 conflicting, 7 insufficient
  - 62 verbatim evidence quotes
  - completed by one pooling round
- **CLI:** `python -m verity search "<query>"` and `python -m verity evaluate`
- **Experiments:** `scripts/m2_experiments.py` → [experiments/m2-bm25.md](experiments/m2-bm25.md)
- **Results** (BM25, k1 = 1.2, b = 0.75, 37 answerable claims):
  - **R@1 0.538, R@5 0.725, R@10 0.815, MRR 0.736**
  - Lexical claims: MRR 0.913. Paraphrased: 0.477.
  - Conflicting claims had both sides in the top 5 for 0 of 5.
- **Reference check:** the Okapi variant matches `rank_bm25` to within 10⁻¹² on every query × passage pair, with identical top-10 lists for 44/44 queries.
- **Bug found by the artifact study and fixed:** the kerning repair was joining real one-letter labels ("B temperatures" → `btemperature`). It is now limited to overhanging capitals T, V, W and Y.
- **Tests:** 239 passing
  - `test_analyze` 25
  - `test_bm25` 25: hand-computed score, Hypothesis checks against the formula and against rank_bm25, missing terms, irrelevant passages, duplicates, length normalization, saturation, long-document dominance
  - `test_evaluation` 21
  - one new CLI test
  - provenance tests updated

## Current limitations

- **Retrieval is lexical.** Paraphrased claims are found far less often (MRR 0.48 vs 0.91 for lexical). The 4 claims with no relevant passage in the top 10 are all paraphrases, and 3 of them are about the most contested questions.
- **Both sides of a dispute are rarely in the top 5** (0/5 conflicting claims). Anything downstream that reads only the top 5 would see one side.
- **The gold set is small and self-built** (37 answerable claims, one annotator, pooled from one system). Differences below about 0.03 MRR are noise. Relevance by quote containment misses paraphrased restatements.
- **BM25 scores can't detect "insufficient"** (AUROC 0.86, overlapping ranges). Near-topic claims (insurance settlement, EPA air safety) score like answerable ones.
- **PDF artifacts are still in the index view:** running headers (46 in the Commission chapter), figure-axis text (Bažant), "intentionally left blank" pages, and footnote markers inside words ("building1"). Search-time repair covers kerning, hyphenation, ligatures and diacritics only. The repairs are heuristics fitted to pypdf output on this corpus.
- **Overlapping passages** take up top-k slots (25 adjacent duplicates in 44 queries).
- **Page numbers** can be recovered from form-feed markers but aren't exposed yet.
- **HTML extraction** relies on site-specific rules, tested only on The Conversation.
- **No archival copy:** if a source changes or disappears online, its drift can be detected but it can't be re-fetched. Bažant's copy was retrieved over plain HTTP (the host's certificate is invalid), so its integrity rests on the recorded hash.
- **From M1:** abbreviation splitting, mid-sentence overlap starts, untuned chunking defaults.

## Next steps (awaiting approval)

**Decisions for the project author**
1. **Hulsey's `source_type`** is `academic`. It is a university-authored research report, and its `publication_status` says it isn't journal-reviewed and its `disclosures` record the advocacy funding. Alternatives are `other`, or a new `report` type for non-journal research reports, which would also fit NIST-style technical reports if they weren't official.
2. **Gold-set policy for reported speech** ("NIST claims X", written in Hulsey) and for hypotheses that are later tested: count them as relevant evidence or not. They are currently excluded.
3. **Approve M2,** or ask for changes.

**Candidates (not started)**
- M3: citation verifier (next on the roadmap).
- Retrieval improvements, ranked in [experiments/m2-bm25.md](experiments/m2-bm25.md) §12: dense/hybrid retrieval (M6), deeper or per-source retrieval for conflicting claims, merging overlapping passages, index-time boilerplate stripping, and a larger gold set with a second annotator.
