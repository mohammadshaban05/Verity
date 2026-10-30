# Progress Log

## Completed milestones

### M0: Project skeleton (2026-10-30)

- uv-managed environment with Python 3.12 pinned (`.python-version`, `requires-python`)
- `src/` layout package `verity`, built with hatchling
- pytest configured; one smoke test checks that the package imports
- ruff configured for lint and format (rules E, F, I, B, UP; line length 100)
- Decision log (`DECISIONS.md`, ADR-001 to ADR-007) and roadmap (`ROADMAP.md`)

## Current limitations

- No functionality yet. The package only imports.
- No corpus downloaded yet.
- No evaluation data yet.

## Next steps

**M1: data models + chunking** (implemented by the project author):
1. `src/verity/models.py`: `Document` and `Passage` Pydantic models with validators
2. `src/verity/ingest.py`: `chunk_document(doc, max_chars, overlap) -> list[Passage]`
3. Mentor provides test specs first (offset round-trip, coverage, bounds, deterministic IDs, edge cases), then reviews the implementation
4. Download one seed document (e.g. a chapter of the 9/11 Commission Report) and record its provenance
