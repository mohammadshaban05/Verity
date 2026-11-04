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
| `bazant-2008-wtc-twin-towers` | academic | Bažant, Le, Greening & Benson, "What Did and Did Not Cause Collapse of WTC Twin Towers in New York": authors' preprint of *J. Eng. Mech.* 134(10), 2008 | 2008-03-31 | Copyrighted; author-hosted copy, local only |
| `hulsey-2020-uaf-wtc7` | academic | Hulsey, Quan & Xiao, "A Structural Reevaluation of the Collapse of World Trade Center 7", UAF INE Report 18.17 | 2020-03 | No license stated; local only |

**Scope and status, as recorded in each record's `publication_status` and `disclosures`:**
- **Bažant et al.:** about the **Twin Towers, not WTC 7**. The text is the authors' preprint; the published journal version may differ. Funding: U.S. DOT grant.
- **Hulsey et al.:** about **WTC 7, not the Twin Towers**. A university report, not a journal article. It names "external peer reviewers", but independent journal peer review is not established. **Funded by Architects & Engineers for 9/11 Truth**, an advocacy organization (project budget $316,153 per the UAF project page).
- **Schneider:** a conference paper; peer review not established.
- **The Conversation:** author Kuligowski's NIST funding and her work on NIST's WTC investigation are disclosed.

These facts are recorded so readers can weigh them. They do not produce a score (ADR-006, ADR-009).

## Rules

- **`source_type` describes a source; it doesn't rate it.** "official" doesn't mean true, and "critique" doesn't mean false.
- **Academic affiliation is not peer review.** `publication_status` states only the review a document actually establishes.
- **Record funding and conflicts in `disclosures`** as the source states them ("None stated" otherwise). Never convert them into a credibility score.
- **Write unknowns explicitly**: `"published": null`, `"authors": []`. Give dates only to the precision actually known (`"2008-11"`).
- **Local-only sources are fine.** To add a paper you can access but can't redistribute (e.g. through a university library), put the text in `raw/` and write its record by hand. Set `rights` accordingly.
- **Never commit source texts** or built snapshots.
