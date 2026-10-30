"""Shared builders for tests. Plain functions (not fixtures) so Hypothesis can use them."""

import hashlib
from datetime import UTC, datetime
from typing import Any

from verity.models import Document, SourceType

FIXED_TIME = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def reference_sha256(text: str) -> str:
    """Independent reference hash, so model tests don't depend on sha256_hex."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def document_kwargs(**overrides: Any) -> dict[str, Any]:
    """Valid Document constructor arguments; override any field."""
    text = overrides.get("text", "The report was published in 2004.")
    kwargs: dict[str, Any] = {
        "id": "test-doc",
        "title": "Test document",
        "source_uri": "test://test-doc",
        "source_type": SourceType.OTHER,
        "retrieved_at": FIXED_TIME,
        "text": text,
        "sha256": reference_sha256(text),
    }
    kwargs.update(overrides)
    return kwargs


def make_doc(text: str, doc_id: str = "test-doc") -> Document:
    """A valid Document with the given text (hash computed by the reference function)."""
    return Document(**document_kwargs(id=doc_id, text=text))
