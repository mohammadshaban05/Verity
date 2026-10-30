# Verity

Verity is a research and evidence-verification tool for contested historical and political questions. It checks claims against a corpus of sources. Every citation must point to an exact, verifiable span of a stored source document, and the system says so plainly when the evidence is insufficient. It separates two questions: *what a source says* (attribution verification) and *whether the underlying claim is true* (claim assessment).

Status: early development. See [docs/PROGRESS.md](docs/PROGRESS.md), [docs/ROADMAP.md](docs/ROADMAP.md), and [docs/DECISIONS.md](docs/DECISIONS.md).

## Development

Requires [uv](https://docs.astral.sh/uv/). It installs and pins Python 3.12 automatically.

```bash
uv sync                      # create .venv and install deps
uv run pytest                # run tests
uv run ruff check .          # lint
uv run ruff format .         # format
```
