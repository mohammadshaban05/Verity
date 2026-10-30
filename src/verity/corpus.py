"""Load a local corpus directory into Documents.

Layout (ADR-009):

    <corpus>/sources/<doc_id>.json   provenance record; small, committed to git
    <corpus>/raw/<doc_id>.txt        source text in UTF-8; local only, never committed

The file name gives the document ID. Any other files in ``raw/`` (such as the
original PDF or HTML a text was extracted from) are kept for auditing and
ignored by the loader.
"""

import re
from pathlib import Path
from typing import Self

from pydantic import ValidationError, model_validator

from verity.models import Document, Provenance, sha256_hex
from verity.normalize import NormalizationError, normalize_bytes

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class SourceRecord(Provenance):
    """Schema of ``sources/<doc_id>.json``."""

    # Hash of the *normalized* text, recorded at first retrieval. Anyone who
    # re-fetches the source can check that they got exactly the same text.
    expected_sha256: str | None = None

    @model_validator(mode="after")
    def _check_expected_hash(self) -> Self:
        if self.expected_sha256 is not None and not _SHA256_PATTERN.fullmatch(self.expected_sha256):
            raise ValueError("expected_sha256 must be 64 lowercase hex characters")
        return self


class CorpusError(ValueError):
    """One or more documents in the corpus are invalid. Lists every problem found."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        details = "\n".join(f"  - {p}" for p in problems)
        super().__init__(f"{len(problems)} corpus problem(s):\n{details}")


class _DocumentProblem(Exception):
    pass


def load_corpus(corpus_dir: Path) -> list[Document]:
    """Load and validate every document, sorted by ID. Raises CorpusError listing
    all problems rather than stopping at the first one, and never skips a bad
    document silently."""
    sources_dir, raw_dir = corpus_dir / "sources", corpus_dir / "raw"
    if not sources_dir.is_dir():
        raise CorpusError([f"{sources_dir}: sources directory not found"])

    problems: list[str] = []
    documents: list[Document] = []
    record_ids: set[str] = set()

    for record_path in sorted(sources_dir.glob("*.json")):
        doc_id = record_path.stem
        record_ids.add(doc_id)
        try:
            documents.append(_load_document(doc_id, record_path, raw_dir / f"{doc_id}.txt"))
        except _DocumentProblem as exc:
            problems.append(str(exc))

    if raw_dir.is_dir():
        for text_path in sorted(raw_dir.glob("*.txt")):
            if text_path.stem not in record_ids:
                problems.append(
                    f"{text_path}: no provenance record (expected sources/{text_path.stem}.json)"
                )

    # The same text under two IDs would later count as two pieces of evidence.
    first_id_by_hash: dict[str, str] = {}
    for doc in documents:
        if doc.sha256 in first_id_by_hash:
            problems.append(
                f"duplicate content: {first_id_by_hash[doc.sha256]!r} and {doc.id!r} "
                "have identical normalized text"
            )
        else:
            first_id_by_hash[doc.sha256] = doc.id

    if problems:
        raise CorpusError(problems)
    return documents


def _load_document(doc_id: str, record_path: Path, text_path: Path) -> Document:
    try:
        record = SourceRecord.model_validate_json(record_path.read_bytes())
    except ValidationError as exc:
        raise _DocumentProblem(
            f"{record_path}: invalid provenance record: {_summarize(exc)}"
        ) from exc

    if not text_path.is_file():
        raise _DocumentProblem(
            f"{text_path}: source text missing; retrieve it from {record.source_uri}"
        )
    try:
        text = normalize_bytes(text_path.read_bytes())
    except NormalizationError as exc:
        raise _DocumentProblem(f"{text_path}: {exc}") from exc

    actual = sha256_hex(text)
    if record.expected_sha256 is not None and actual != record.expected_sha256:
        raise _DocumentProblem(
            f"{text_path}: normalized text has sha256 {actual[:12]}..., but the record "
            f"expects {record.expected_sha256[:12]}... (file corrupted or edited, or a "
            "different version of the source)"
        )

    try:
        return Document.from_text(id=doc_id, text=text, provenance=record)
    except ValidationError as exc:
        raise _DocumentProblem(f"{record_path}: {_summarize(exc)}") from exc


def _summarize(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        parts.append(f"{location}: {error['msg']}" if location else error["msg"])
    return "; ".join(parts)
