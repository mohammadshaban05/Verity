"""Core data models: source documents and the passages cut from them.

Offset convention (ADR-008): every offset is a half-open interval [start, end)
of Python ``str`` indices (Unicode code points) into ``Document.text``. Never bytes.
"""

import hashlib
import re
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

# Document IDs are embedded in passage IDs ("<doc_id>@<hash>:<start>-<end>") and in
# filenames, so they must not contain separators such as "@", ":", "/" or whitespace.
_DOC_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]+")


class SourceType(StrEnum):
    """Broad category of a source (ADR-006). Used later for claim assessment, never as a
    shortcut for truth."""

    OFFICIAL = "official"
    JOURNALISM = "journalism"
    ACADEMIC = "academic"
    CRITIQUE = "critique"
    OTHER = "other"


def sha256_hex(text: str) -> str:
    """Return the lowercase hex SHA-256 digest of ``text`` encoded as UTF-8.

    Hashes the exact code points given. No Unicode or whitespace normalization
    happens here; normalization belongs to the loader, before a Document exists.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Document(BaseModel):
    """An immutable snapshot of one source's text plus its provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    source_uri: str
    source_type: SourceType
    retrieved_at: datetime
    text: str
    sha256: str

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        if not _DOC_ID_PATTERN.fullmatch(self.id):
            raise ValueError(f"id must match [A-Za-z0-9._-]+, got {self.id!r}")
        if not self.title:
            raise ValueError("title must not be empty")
        if not self.source_uri:
            raise ValueError("source_uri must not be empty")
        if not self.text:
            # Whitespace-only text is allowed; truly empty text means ingestion failed.
            raise ValueError("text must not be empty")
        if self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        # Integrity check: runs on every construction, including loading stored JSON,
        # so a corrupted or edited snapshot can never be loaded silently.
        if self.sha256 != sha256_hex(self.text):
            raise ValueError("sha256 does not match text")
        return self

    @classmethod
    def from_text(
        cls,
        *,
        id: str,
        title: str,
        source_uri: str,
        source_type: SourceType,
        retrieved_at: datetime,
        text: str,
    ) -> "Document":
        """Build a Document, computing its hash from ``text``."""
        return cls(
            id=id,
            title=title,
            source_uri=source_uri,
            source_type=source_type,
            retrieved_at=retrieved_at,
            text=text,
            sha256=sha256_hex(text),
        )


class Passage(BaseModel):
    """A contiguous slice ``Document.text[start:end]`` of one document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    doc_id: str
    start: int
    end: int
    text: str

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        if not self.id or not self.doc_id:
            raise ValueError("id and doc_id must not be empty")
        if not 0 <= self.start < self.end:
            raise ValueError(f"need 0 <= start < end, got start={self.start}, end={self.end}")
        if len(self.text) != self.end - self.start:
            raise ValueError(
                f"text length {len(self.text)} does not match span length {self.end - self.start}"
            )
        # A Passage can't check its text against the document, because it has no
        # access to the document. The chunker guarantees and tests that property.
        return self
