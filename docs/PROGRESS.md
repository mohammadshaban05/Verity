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
- **Seed corpus at the time:** 4 documents (575 passages) on a single topic, the collapse of the World Trade Center buildings. The project author had mentioned that topic only to illustrate the kind of contested question Verity might eventually investigate. The documents were a mix of public-domain and copyrighted sources, so only their provenance records were committed. **This corpus was replaced in the dataset migration below.**
- **Reproducibility checks on that corpus:**
  - re-downloading every source from scratch reproduced every recorded hash
  - two independent builds produced byte-identical snapshot files
  - `verify` re-chunks the documents and gets identical passages
- **Tests:** 158 passing
  - 16 normalization tests, including a Hypothesis idempotence test
  - 32 corpus tests covering corrupted documents, missing metadata, duplicates, encoding errors and multi-problem reporting
  - 20 store tests covering round trip, byte-identical rebuilds, and corruption caught both by file hashes and by semantic checks
  - 2 CLI tests and 4 HTML-extractor tests
  - model tests grew from 36 to 52 with the new provenance rules

### M2: BM25 retrieval + evaluation (2026-10-30, first run on the earlier corpus)

- **Corpus extended** to 6 documents and 909 passages, still on the single example topic.
- **Provenance:** new required fields `affiliations`, `publication_status` and `disclosures`. Academic affiliation is not treated as peer review, and funding is recorded, never scored (ADR-009, data/corpus/README.md).
- **`src/verity/retrieval/`:**
  - `Retriever` protocol and `SearchHit`
  - `Analyzer`: search-time PDF-artifact repair, NFKC, folding, stopwords, S-stemmer (ADR-011)
  - `BM25Retriever`: hand-written inverted index, Lucene and Okapi idf, `explain()`
- **`src/verity/evaluation.py`:** gold-set schema in which the label must follow from the evidence stances; quote → passage resolution; Recall@k, MRR, and a both-sides check (ADR-012)
- **Gold set (first version):** 44 hand-written claims (22 supported, 10 contradicted, 5 conflicting, 7 insufficient), 62 verbatim evidence quotes, completed by one pooling round. Phrasing (lexical vs paraphrase) was annotated by hand.
- **CLI:** `python -m verity search "<query>"` and `python -m verity evaluate`
- **Experiments:** `scripts/m2_experiments.py`
- **Results on that corpus, now superseded** (BM25, k1 = 1.2, b = 0.75, 37 answerable claims):
  - MRR **0.611** before pooling, **0.736** after (R@1 0.538, R@5 0.725, R@10 0.815)
  - lexical claims MRR 0.913, paraphrased 0.477; conflicting claims had both sides in the top 5 for 0 of 5
  - these numbers describe that corpus and gold set only, and are **not comparable** with the current results below; the full report is in git history (commit `a8489c8`, `docs/experiments/m2-bm25.md`)
- **Reference check:** the Okapi variant matches `rank_bm25` to within 10⁻¹² on every query × passage pair (44/44 identical top-10 lists).
- **Bug found by the artifact study and fixed:** the kerning repair was joining real one-letter labels ("B temperatures" → `btemperature`). It was limited to overhanging capitals T, V, W and Y.
- **Tests:** 239 passing

### Dataset migration: general-purpose seed corpus (2026-11-03, awaiting review)

**Why.** The project author clarified that the single-topic corpus was only ever an example. Verity is a general-purpose evidence-verification platform, so its development corpus has to be neutral, multi-subject and redistributable (ADR-013).

**What changed**
- **Corpus:** 97 documents, 1,090 passages, all redistributable, texts committed (`data/corpus/raw/*.txt`):
  - 17 English Wikipedia articles, each pinned to one revision (CC BY-SA 4.0): 9 on FEVER subjects (history, geology, biology, music, literature, technology, geography, anatomy, astronomy) and 8 that WikiContradict reports as contradicting themselves
  - 5 Simple English Wikipedia articles on FEVER subjects, as independent second sources
  - 75 SciFact abstracts (ODC-By 1.0): the evidence for a seeded, label-stratified sample of 16 SciFact dev claims, plus 60 random distractors
- **Scripts:** `scripts/select_corpus.py` (new) records which documents are in the corpus and why. `scripts/fetch_corpus.py` gained MediaWiki-revision and SciFact fetchers and a Wikipedia prose extractor. The PDF and HTML paths are unchanged.
- **Gold set** rebuilt: 50 claims in 13 topics, 88 verbatim quotes. 23 adapted from FEVER, 16 from SciFact, 8 from WikiContradict, and 3 written for Verity (cross-source agreement and conflict). Every FEVER label was re-checked against the pinned revision, and 4 differ from FEVER (see `data/eval/README.md`).
- **Evaluation methodology:**
  - Each claim records its `origin`, and results are broken down by dataset.
  - Phrasing is now **measured** (lexical if at least half of the claim's index terms occur in its closest quote) instead of annotated.
  - Pooling was repeated: 5 claims gained direct evidence; every insufficient claim was checked against the whole corpus.
- **Analyzer default:** PDF-artifact repair is now **off** (ADR-011). On this corpus, all 39 kerning-rule matches are false joins of real one-letter words, such as "T cells" → `tcell`. It stays available for PDF-derived text.
- **New source type** `reference` for encyclopedias and other tertiary sources (Wikipedia).
- **Unchanged:** BM25, chunking, normalization, hashing, snapshots, the evidence/label rules (ADR-012) and the metrics.
- **Tests and code:** case-study examples in tests, comments and the experiments script were replaced with neutral ones. New tests cover the Wikipedia extractor, SciFact text, fetch dispatch, measured phrasing, `origin`, the committed corpus loading against its hashes, and the gold set resolving on a fresh clone without `ingest`.

**Results** (BM25, k1 = 1.2, b = 0.75, default analyzer, 41 answerable claims). Full report: [experiments/m2-bm25.md](experiments/m2-bm25.md)

| | R@1 | R@5 | R@10 | MRR |
|---|---:|---:|---:|---:|
| before pooling | 0.398 | 0.821 | 0.896 | 0.747 |
| **after pooling** | **0.423** | **0.837** | **0.896** | **0.803** |

- R@1 has a ceiling of 0.648 on this gold set, because many claims have evidence in more than one passage.
- Every answerable claim has a relevant passage in the top 10.
- **By label (MRR):** supported 0.844, contradicted 0.663, conflicting 0.950.
- **By phrasing (MRR):** lexical 0.902, paraphrase 0.677.
- **Both sides of a conflict:** in the top 5 for 6 of 10 conflicting claims, and in the top 20 for all 10.
- **rank_bm25 parity:** 50/50 identical top-10 lists; max score difference 3.4 × 10⁻¹³.
- **Insufficient detection by top-1 score:** AUROC 0.722.
- **Tests:** 252 passing.

## Current limitations

- **Retrieval is lexical.** Paraphrased claims score MRR 0.68, against 0.90 for lexical ones. Contradicted claims score lowest (0.66), because the word that makes a claim false ("newspaper", "NGO") often never occurs in the source.
- **The gold set is small.**
  - 41 answerable claims, pooled from one system. Differences below about 0.024 MRR are noise.
  - Most topics have 1–4 claims.
  - Only **2 conflicts are between different sources**; the other 8 are inside one article.
  - Relevance by quote containment misses paraphrased restatements.
- **Adapted datasets.** FEVER labels were re-derived against 2026 revisions, and WikiContradict quotes were re-taken from the pinned revisions. Results are not comparable with published benchmark numbers.
- **The analyzer default is open to question.** On this corpus the raw analyzer (no stopwords, no stemming) beats the default by +0.067 MRR [+0.017, +0.131], driven by 7 claims. The default was not changed, because that would be tuning on the test set.
- **BM25 scores can't detect "insufficient"** (AUROC 0.72). One insufficient claim scores above most answerable claims.
- **Overlapping passages** take up top-k slots (61 adjacent duplicates in 50 queries).
- **Wikipedia re-rendering.** MediaWiki renders old revisions with current templates, so a re-fetch can drift from the recorded hash. The committed texts are the reference copy.
- **SciFact metadata** (authors, venue, date) is not recorded, and each record says so.
- **Still untested on PDFs.** The corpus has no PDFs, so the PDF path of `fetch_corpus.py` and the repair rules are now exercised only by unit tests.
- **From M1:** abbreviation splitting, mid-sentence overlap starts, untuned chunking defaults.

## Next steps (awaiting approval)

**Decisions for the project author**
1. **Review the dataset migration**, especially:
   - the four FEVER label changes and the five pooling additions (`data/eval/README.md`, experiment report §2);
   - the license chosen for the gold set (CC BY-SA 4.0, because it quotes CC BY-SA text);
   - the new `reference` source type.
2. **Analyzer default.** Keep stopwords and stemming, or decide the question on a held-out split once the gold set grows (experiment report §4).
3. **Gold-set policy for reported speech and for hypotheses** ("X claims that…", "the leading hypothesis was…"): count them as relevant evidence or not. They are currently excluded, as in the first M2 run.
4. **Git history** still contains the provenance records and gold set of the earlier corpus (commit `11b638e` onwards). Leave it, which is accurate history and contains no copyrighted text, or rewrite it.
5. **Repository license.** There is no root `LICENSE` for the code yet. The data licenses are documented in `data/corpus/README.md` and `data/eval/README.md`.
6. **Approve M2 with the new corpus,** or ask for changes.

**Candidates (not started)**
- M3: citation verifier (next on the roadmap).
- Retrieval improvements, ranked in [experiments/m2-bm25.md](experiments/m2-bm25.md) §12: dense/hybrid retrieval (M6), deeper or per-source retrieval, more cross-source conflicts and a held-out split in the gold set, and merging overlapping passages.
