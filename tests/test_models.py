"""Specification tests for Document, Passage and sha256_hex (Milestone 1)."""

import unicodedata
from datetime import datetime

import pytest
from pydantic import ValidationError

from factories import FIXED_TIME, document_kwargs, reference_sha256
from verity.models import Document, Passage, SourceType, sha256_hex

# --- sha256_hex ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Standard SHA-256 test vectors.
        ("", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
        ("abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
    ],
)
def test_sha256_hex_matches_known_vectors(text: str, expected: str) -> None:
    assert sha256_hex(text) == expected


def test_sha256_hex_uses_utf8_for_non_ascii() -> None:
    text = "NIST — بيان — 报告 — 🔍"
    assert sha256_hex(text) == reference_sha256(text)


def test_sha256_hex_does_not_normalize_unicode() -> None:
    # "é" as one code point (NFC) vs "e" + combining accent (NFD): they look
    # identical but are different text, so their offsets and hashes must differ.
    nfc = unicodedata.normalize("NFC", "café")
    nfd = unicodedata.normalize("NFD", "café")
    assert nfc != nfd
    assert sha256_hex(nfc) != sha256_hex(nfd)


# --- Document: valid construction --------------------------------------------------


def test_document_accepts_valid_input() -> None:
    doc = Document(**document_kwargs())
    assert doc.source_type is SourceType.OTHER


def test_document_from_text_computes_hash() -> None:
    doc = Document.from_text(
        id="nist-ncstar-1a",
        title="Final Report on the Collapse of WTC Building 7",
        source_uri="https://example.org/ncstar1a.pdf",
        source_type=SourceType.OFFICIAL,
        retrieved_at=FIXED_TIME,
        text="Some text.",
    )
    assert doc.sha256 == reference_sha256("Some text.")


def test_document_accepts_source_type_as_string() -> None:
    doc = Document(**document_kwargs(source_type="academic"))
    assert doc.source_type is SourceType.ACADEMIC


def test_document_json_round_trip_is_lossless() -> None:
    doc = Document(**document_kwargs(text="Line one.\n\nLine two — ünïcödé 🔍"))
    assert Document.model_validate_json(doc.model_dump_json()) == doc


def test_document_accepts_whitespace_only_text() -> None:
    # Strange but not corrupt; the chunker returns [] for it.
    Document(**document_kwargs(text="  \n\t "))


# --- Document: rejection rules -----------------------------------------------------


@pytest.mark.parametrize(
    "bad_hash",
    [
        "0" * 64,  # well-formed but wrong
        reference_sha256("The report was published in 2004.").upper(),  # not canonical
        "",
    ],
)
def test_document_rejects_hash_not_matching_text(bad_hash: str) -> None:
    with pytest.raises(ValidationError):
        Document(**document_kwargs(sha256=bad_hash))


def test_document_rejects_empty_text() -> None:
    with pytest.raises(ValidationError):
        Document(**document_kwargs(text=""))


def test_document_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError):
        Document(**document_kwargs(retrieved_at=datetime(2026, 10, 30, 12, 0)))


@pytest.mark.parametrize("bad_id", ["", "has space", "a/b", "a:b", "tab\there"])
def test_document_rejects_bad_id(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        Document(**document_kwargs(id=bad_id))


@pytest.mark.parametrize("good_id", ["911-commission-ch1", "NCSTAR_1A", "v1.2"])
def test_document_accepts_slug_ids(good_id: str) -> None:
    Document(**document_kwargs(id=good_id))


@pytest.mark.parametrize("field", ["title", "source_uri"])
def test_document_rejects_empty_metadata(field: str) -> None:
    with pytest.raises(ValidationError):
        Document(**document_kwargs(**{field: ""}))


def test_document_rejects_unknown_source_type() -> None:
    with pytest.raises(ValidationError):
        Document(**document_kwargs(source_type="blog-i-trust"))


def test_document_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Document(**document_kwargs(sha265="typo"))


def test_document_is_immutable() -> None:
    doc = Document(**document_kwargs())
    with pytest.raises(ValidationError):
        doc.text = "Edited after hashing."  # type: ignore[misc]


# --- Passage -----------------------------------------------------------------------


def passage_kwargs(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "id": "p1",
        "doc_id": "test-doc",
        "start": 4,
        "end": 10,
        "text": "report",
    }
    kwargs.update(overrides)
    return kwargs


def test_passage_accepts_valid_input() -> None:
    p = Passage(**passage_kwargs())
    assert (p.start, p.end, p.text) == (4, 10, "report")


@pytest.mark.parametrize(
    "overrides",
    [
        {"start": -1, "end": 5, "text": "repor"},  # negative start
        {"start": 5, "end": 5, "text": ""},  # empty span
        {"start": 10, "end": 4},  # reversed span
        {"text": "too long for span"},  # length mismatch
        {"text": "short"},  # length mismatch
        {"id": ""},
        {"doc_id": ""},
    ],
)
def test_passage_rejects_invalid_spans(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Passage(**passage_kwargs(**overrides))


def test_passage_is_immutable() -> None:
    p = Passage(**passage_kwargs())
    with pytest.raises(ValidationError):
        p.start = 0  # type: ignore[misc]
