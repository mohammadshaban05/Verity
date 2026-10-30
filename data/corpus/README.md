# Corpus

**Topic:** the collapse of the World Trade Center buildings on September 11, 2001.

```
sources/<id>.json   provenance record (committed)
raw/<id>.txt        extracted text, UTF-8 (local only, gitignored)
raw/<id>.pdf|.html  original download, kept to audit the extraction (gitignored)
```

The file name gives the document ID. Texts aren't committed, because some sources are copyrighted. Instead, each record stores `expected_sha256`: the hash of the normalized text. Running `scripts/fetch_corpus.py` re-downloads every source and reports whether your copy matches.

## Sources

| id | type | source | published | rights |
|---|---|---|---|---|
| `911-commission-ch9` | official | National Commission on Terrorist Attacks Upon the United States, *The 9/11 Commission Report*, ch. 9 "Heroism and Horror" | 2004-07-22 | Public domain (U.S.) |
| `nist-ncstar-1a` | official | NIST, *Final Report on the Collapse of World Trade Center Building 7* (NCSTAR 1A) | 2008-11 | U.S. government work |
| `conversation-2021-twin-towers-collapse` | journalism | The Conversation; Oswald, Kuligowski & Nguyen | 2021-09-08 | CC BY-ND 4.0 |
| `schneider-2019-wtc-structural-dynamics` | academic | Schneider, "The Structural Dynamics of the World Trade Center Catastrophe", arXiv:1910.10801v2 (IABSE Congress 2019) | 2019-10-25 | arXiv non-exclusive license |

## Rules

- **`source_type` describes a source; it doesn't rate it.** "official" doesn't mean true, and "critique" doesn't mean false.
- **Write unknowns explicitly**: `"published": null`, `"authors": []`. Give dates only to the precision actually known (`"2008-11"`).
- **Local-only sources are fine.** To add a paper you can access but can't redistribute (e.g. through a university library), put the text in `raw/` and write its record by hand. Set `rights` accordingly.
- **Never commit source texts** or built snapshots.
