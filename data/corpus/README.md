# Corpus

The seed corpus is a small, **multi-subject, redistributable** collection for developing and evaluating retrieval and verification (ADR-013). It is not about any one topic. The gold claims in [`../eval/claims.jsonl`](../eval/claims.jsonl) are evaluated against it.

```
sources/<id>.json      provenance record (committed)
raw/<id>.txt           extracted text, UTF-8 (committed)
raw/<id>.html|.json    original download, kept locally to audit the extraction (gitignored)
```

The file name is the document ID. Each record stores `expected_sha256`, the hash of the normalized text. The loader checks every text against it, so an edited or corrupted text is rejected.

| Collection | Documents | Passages* | License |
|---|---:|---:|---|
| English Wikipedia articles, each pinned to one revision | 17 | 900 | CC BY-SA 4.0 |
| Simple English Wikipedia articles, each pinned to one revision | 5 | 13 | CC BY-SA 4.0 |
| SciFact abstracts (Wadden et al., 2020) | 75 | 177 | ODC-By 1.0 |

\* With the default chunking (1000 characters, 200 overlap).

## Rebuilding and checking

```bash
uv run python scripts/select_corpus.py            # (re)write sources/*.json; keeps recorded hashes
uv run --group corpus python scripts/fetch_corpus.py   # re-download every text and compare hashes
```

The texts are committed, so neither script is needed to run the tests or the benchmarks. `fetch_corpus.py` exists to show the texts can be reproduced from their sources:

- **Wikipedia.** It fetches the pinned revision through the MediaWiki parse API (`action=parse&oldid=N`) and keeps the article prose: paragraphs, headings, list items and quotations. It drops tables, infoboxes, figures, citation markers and everything from "See also" / "References" onwards.
  - Caveat: MediaWiki renders old revisions with *current* templates. A re-fetch can therefore differ slightly even for a fixed revision, and the hash check reports this as `DRIFT`.
- **SciFact.** It reads the abstract from the SciFact release tarball. The text is the title, a blank line, then the abstract sentences joined by single spaces.

## Sources

### Wikipedia (22 articles)

FEVER claims refer to these articles; each is pinned to the revision that was current when the corpus was built (November 2026). WikiContradict articles are pinned to an earlier revision in which **both** sides of the reported contradiction are in the article prose. Simple English articles are separately written second sources on five of the FEVER subjects. One of them, Yandex's launch date, disagrees with the English article.

| id | article | revision | date | why it is included |
|---|---|---|---|---|
| `wiki-cretaceous` | Cretaceous | [1383605539](https://en.wikipedia.org/w/index.php?oldid=1383605539) | 2026-11-03 | FEVER |
| `wiki-dodo` | Dodo | [1375347989](https://en.wikipedia.org/w/index.php?oldid=1375347989) | 2026-09-17 | FEVER |
| `wiki-elizabeth-of-york` | Elizabeth of York | [1381204294](https://en.wikipedia.org/w/index.php?oldid=1381204294) | 2026-10-20 | FEVER |
| `wiki-heart` | Heart | [1383668909](https://en.wikipedia.org/w/index.php?oldid=1383668909) | 2026-11-04 | FEVER |
| `wiki-hindu-kush` | Hindu Kush | [1376768386](https://en.wikipedia.org/w/index.php?oldid=1376768386) | 2026-09-26 | FEVER |
| `wiki-near-earth-object` | Near-Earth object | [1376698751](https://en.wikipedia.org/w/index.php?oldid=1376698751) | 2026-09-25 | FEVER |
| `wiki-philip-glass` | Philip Glass | [1382501805](https://en.wikipedia.org/w/index.php?oldid=1382501805) | 2026-10-29 | FEVER |
| `wiki-sancho-panza` | Sancho Panza | [1379920596](https://en.wikipedia.org/w/index.php?oldid=1379920596) | 2026-10-12 | FEVER |
| `wiki-yandex` | Yandex | [1382077537](https://en.wikipedia.org/w/index.php?oldid=1382077537) | 2026-10-26 | FEVER |
| `wiki-acne` | Acne | [1206513250](https://en.wikipedia.org/w/index.php?oldid=1206513250) | 2024-02-12 | WikiContradict |
| `wiki-aedes-albopictus` | Aedes albopictus | [1209117076](https://en.wikipedia.org/w/index.php?oldid=1209117076) | 2024-02-20 | WikiContradict |
| `wiki-bremen` | Bremen | [1208767633](https://en.wikipedia.org/w/index.php?oldid=1208767633) | 2024-02-18 | WikiContradict |
| `wiki-cd19` | CD19 | [1199269744](https://en.wikipedia.org/w/index.php?oldid=1199269744) | 2024-01-26 | WikiContradict |
| `wiki-chartreuse-liqueur` | Chartreuse (liqueur) | [1194284821](https://en.wikipedia.org/w/index.php?oldid=1194284821) | 2024-01-08 | WikiContradict |
| `wiki-loretto-chapel` | Loretto Chapel | [1191210227](https://en.wikipedia.org/w/index.php?oldid=1191210227) | 2023-12-22 | WikiContradict |
| `wiki-munsee-language` | Munsee language | [1204134377](https://en.wikipedia.org/w/index.php?oldid=1204134377) | 2024-02-06 | WikiContradict |
| `wiki-torpedo` | Torpedo | [1210926479](https://en.wikipedia.org/w/index.php?oldid=1210926479) | 2024-02-29 | WikiContradict |
| `simplewiki-cretaceous` | Cretaceous | [10991469](https://simple.wikipedia.org/w/index.php?oldid=10991469) | 2026-09-10 | second source |
| `simplewiki-dodo` | Dodo | [11027682](https://simple.wikipedia.org/w/index.php?oldid=11027682) | 2026-10-12 | second source |
| `simplewiki-elizabeth-of-york` | Elizabeth of York | [10969547](https://simple.wikipedia.org/w/index.php?oldid=10969547) | 2026-08-21 | second source |
| `simplewiki-near-earth-object` | Near-Earth object | [10427113](https://simple.wikipedia.org/w/index.php?oldid=10427113) | 2025-07-30 | second source |
| `simplewiki-yandex` | Yandex | [10458131](https://simple.wikipedia.org/w/index.php?oldid=10458131) | 2025-08-15 | second source |

Dates are revision timestamps in UTC. Wikipedia is a tertiary source (`source_type: "reference"`). It is written by volunteer editors and is not peer-reviewed, and the corpus records exactly that.

### SciFact (75 abstracts)

[SciFact](https://github.com/allenai/scifact) pairs expert-written scientific claims with abstracts annotated as supporting or contradicting them. `scripts/select_corpus.py` draws a seeded, label-stratified sample of 16 claims from the dev split: 6 SUPPORT, 5 CONTRADICT and 5 NOT ENOUGH INFO. It adds every abstract those claims cite, plus 60 random distractor abstracts from the rest of the SciFact corpus. Each record's `publication_status` states why the abstract was selected.

SciFact does not record authors, venues or dates. The records leave those fields empty (`"authors": []`, `"published": null`) and say so, rather than guessing.

## Licenses and attribution

The texts in `raw/` are redistributed under their original licenses:

- **Wikipedia articles**: © Wikipedia contributors, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Each `raw/wiki-*.txt` and `raw/simplewiki-*.txt` is a text-only extraction of the revision linked in its record. The full list of authors is in that revision's history. **Changes:** markup, tables, figures, citation markers and end matter were removed, and whitespace was normalized. The extracted texts are distributed under the same license.
- **SciFact abstracts**: from S2ORC via SciFact (Wadden et al., "Fact or Fiction: Verifying Scientific Claims", EMNLP 2020), [ODC-By 1.0](https://opendatacommons.org/licenses/by/1-0/). **Changes:** sentences were joined into one paragraph and whitespace was normalized.

Each record's `rights` field repeats the applicable license.

## Rules

- **`source_type` describes a source; it does not rate it.** "official" doesn't mean true, "reference" doesn't mean neutral, and "critique" doesn't mean false.
- **Academic affiliation is not peer review.** `publication_status` states only the review a document actually establishes.
- **Record funding and conflicts in `disclosures`** as the source states them ("None stated" otherwise). Never convert them into a credibility score.
- **Write unknowns explicitly**: `"published": null`, `"authors": []`. Give dates only to the precision actually known (`"2008-11"`).
- **Commit only texts that may be redistributed.** A source you can read but not redistribute (e.g. a paywalled paper) can still be used locally. Put its text in `raw/`, write its record by hand with the correct `rights`, and keep it out of commits: add its path to `.gitignore`, and keep its claims out of the committed gold set.
- **Pin versions.** A source that changes (a wiki page, a living document) must be recorded at a fixed revision. Otherwise the gold quotes and hashes stop matching.
