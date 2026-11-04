# Verity

Verity is a general-purpose AI research and evidence-verification platform. It checks claims against a corpus of sources. Every citation must point to an exact, verifiable span of a stored source document, and the system says so plainly when the evidence is insufficient. It keeps documented facts, allegations, interpretations and open questions apart. It also separates two questions: *what a source says* (attribution verification) and *whether the underlying claim is true* (claim assessment). Agreement between language models is never treated as verification.

Status: early development. See [docs/PROGRESS.md](docs/PROGRESS.md), [docs/ROADMAP.md](docs/ROADMAP.md), and [docs/DECISIONS.md](docs/DECISIONS.md).

## Development

Requires [uv](https://docs.astral.sh/uv/). It installs and pins Python 3.12 automatically.

```bash
uv sync                      # create .venv and install deps
uv run pytest                # run tests (no network or downloads needed)
uv run ruff check .          # lint
uv run ruff format .         # format
```

## Corpus and snapshots

The seed corpus is a small, multi-subject, redistributable collection: pinned Wikipedia revisions (CC BY-SA 4.0) and SciFact abstracts (ODC-By 1.0). Its texts are committed, so a fresh clone works offline:

```bash
uv run python -m verity ingest --overwrite   # load, normalize, chunk -> data/snapshots/current
uv run python -m verity verify               # integrity + reproducibility check
```

Sources, licenses, attribution and how to re-fetch them are in [data/corpus/README.md](data/corpus/README.md). The gold claims and how they were adapted from FEVER, SciFact and WikiContradict are in [data/eval/README.md](data/eval/README.md).

## Search and evaluation

```bash
uv run python -m verity search "dodo extinction introduced animals" -k 5   # BM25 over the snapshot
uv run python -m verity evaluate                    # Recall@k / MRR on data/eval/claims.jsonl
uv run python scripts/m2_experiments.py             # reference comparison, ablations, failure analysis
```

Results and failure analysis: [docs/experiments/m2-bm25.md](docs/experiments/m2-bm25.md).

## Data licenses

Code license: not chosen yet. Corpus texts keep their original licenses (see [data/corpus/README.md](data/corpus/README.md)). The gold set is CC BY-SA 4.0 (see [data/eval/README.md](data/eval/README.md)).
