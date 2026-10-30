"""Core data models: source documents and the passages cut from them.

Offset convention (ADR-008): every offset is a half-open interval [start, end)
of Python ``str`` indices (Unicode code points) into ``Document.text``. Never bytes.
"""

import hashlib
import re
from datetime import date, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

# Document IDs are embedded in passage IDs ("<doc_id>@<hash>:<start>-<end>") and in
# filenames, so they must not contain separators such as "@", ":", "/" or whitespace.
_DOC_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
_PARTIAL_DATE_PATTERN = re.compile(r"\d{4}(-\d{2}(-\d{2})?)?")


class SourceType(StrEnum):
    """What kind of source a document is (ADR-006).

    This is descriptive metadata only. It is never a credibility score: an
    official report is not assumed true, and a critique is not assumed false.
    Claim assessment (later milestones) weighs evidence; it does not trust labels.
    """

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


class Provenance(BaseModel):
    """Where a text came from and under what terms.

    ``published`` and ``authors`` are required keys even when unknown (``null`` /
    ``[]``), so "unknown" is always a deliberate statement, never a forgotten field.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    source_name: str  # publisher, agency or outlet
    authors: tuple[str, ...]  # people; empty for institutional authorship
    source_uri: str  # the exact URL or location the text was retrieved from
    source_type: SourceType
    published: str | None  # ISO 8601 at the precision known: "2008", "2008-11" or "2008-11-20"
    retrieved_at: datetime
    rights: str  # license or copyright status, e.g. "CC BY-ND 4.0"

    @model_validator(mode="after")
    def _check_provenance(self) -> Self:
        for name in ("title", "source_name", "source_uri", "rights"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if any(not author.strip() for author in self.authors):
            raise ValueError("authors must not contain empty names")
        if self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        if self.published is not None:
            _check_partial_date(self.published)
            retrieved = self.retrieved_at.date().isoformat()[: len(self.published)]
            if self.published > retrieved:
                raise ValueError(
                    f"published ({self.published}) is after retrieved_at ({retrieved})"
                )
        return self


def _check_partial_date(value: str) -> None:
    """Accept YYYY, YYYY-MM or YYYY-MM-DD, and only real calendar dates."""
    if not _PARTIAL_DATE_PATTERN.fullmatch(value):
        raise ValueError(f"published must be YYYY, YYYY-MM or YYYY-MM-DD, got {value!r}")
    year, month, day = (value.split("-") + ["01", "01"])[:3]
    try:
        date(int(year), int(month), int(day))
    except ValueError as exc:
        raise ValueError(f"published is not a real date: {value!r}") from exc


class Document(Provenance):
    """An immutable snapshot of one source's text plus its provenance."""

    id: str
    text: str
    sha256: str

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        if not _DOC_ID_PATTERN.fullmatch(self.id):
            raise ValueError(f"id must match [A-Za-z0-9._-]+, got {self.id!r}")
        if not self.text:
            # Whitespace-only text is allowed; truly empty text means ingestion failed.
            raise ValueError("text must not be empty")
        # Integrity check: runs on every construction, including loading stored JSON,
        # so a corrupted or edited snapshot can never be loaded silently.
        if self.sha256 != sha256_hex(self.text):
            raise ValueError("sha256 does not match text")
        return self

    @classmethod
    def from_text(cls, *, id: str, text: str, provenance: Provenance) -> "Document":
        """Build a Document from already-normalized text, computing its hash."""
        fields = {name: getattr(provenance, name) for name in Provenance.model_fields}
        return cls(id=id, text=text, sha256=sha256_hex(text), **fields)

    @property
    def provenance(self) -> Provenance:
        return Provenance(**{name: getattr(self, name) for name in Provenance.model_fields})


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
