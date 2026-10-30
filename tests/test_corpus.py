"""Corpus loader: provenance validation, normalization, and error reporting."""

import json
import unicodedata
from pathlib import Path
from typing import Any

import pytest

from factories import reference_sha256
from verity.corpus import CorpusError, load_corpus
from verity.ingest import chunk_document
from verity.models import SourceType

TEXT = "The North Tower was struck first.\n\nThe South Tower collapsed first.\n"


def record(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "title": "Test source",
        "source_name": "Test Publisher",
        "authors": ["A. Author"],
        "source_uri": "https://example.org/source",
        "source_type": "official",
        "published": "2004-07-22",
        "retrieved_at": "2026-10-30T12:00:00Z",
        "rights": "Public domain",
    }
    data.update(overrides)
    return data


def add_source(
    corpus: Path,
    doc_id: str,
    text: bytes | str | None = TEXT,
    meta: dict[str, Any] | None = None,
    raw_meta: str | None = None,
) -> None:
    """Write sources/<id>.json and (unless text is None) raw/<id>.txt."""
    (corpus / "sources").mkdir(parents=True, exist_ok=True)
    (corpus / "raw").mkdir(parents=True, exist_ok=True)
    payload = raw_meta if raw_meta is not None else json.dumps(meta or record())
    (corpus / "sources" / f"{doc_id}.json").write_text(payload, encoding="utf-8")
    if text is not None:
        data = text.encode("utf-8") if isinstance(text, str) else text
        (corpus / "raw" / f"{doc_id}.txt").write_bytes(data)


def problems_of(corpus: Path) -> list[str]:
    with pytest.raises(CorpusError) as excinfo:
        load_corpus(corpus)
    return excinfo.value.problems


# --- Successful loading ---------------------------------------------------------


def test_loads_documents_sorted_with_provenance(tmp_path: Path) -> None:
    add_source(tmp_path, "b-doc", "Second document.", record(source_type="journalism"))
    add_source(tmp_path, "a-doc", "First document.", record(published=None, authors=[]))

    docs = load_corpus(tmp_path)

    assert [d.id for d in docs] == ["a-doc", "b-doc"]
    assert docs[0].published is None and docs[0].authors == ()
    assert docs[1].source_type is SourceType.JOURNALISM
    assert docs[1].source_name == "Test Publisher"
    assert docs[1].retrieved_at.utcoffset() is not None


def test_text_is_normalized_before_hashing(tmp_path: Path) -> None:
    raw = "﻿Café report.\r\nLine two.\r\n"
    add_source(tmp_path, "doc", raw.encode("utf-8"))

    [doc] = load_corpus(tmp_path)

    assert doc.text == "Café report.\nLine two.\n"
    assert doc.sha256 == reference_sha256(doc.text)


def test_passage_offsets_are_valid_against_normalized_text(tmp_path: Path) -> None:
    raw = ("Café finding.\r\n" * 200).encode("utf-8")
    add_source(tmp_path, "doc", raw)

    [doc] = load_corpus(tmp_path)
    passages = chunk_document(doc, max_chars=100, overlap=20)

    assert passages
    assert all(doc.text[p.start : p.end] == p.text for p in passages)
    assert all("\r" not in p.text for p in passages)


def test_expected_sha256_is_verified_when_present(tmp_path: Path) -> None:
    add_source(tmp_path, "doc", TEXT, record(expected_sha256=reference_sha256(TEXT)))
    assert load_corpus(tmp_path)[0].sha256 == reference_sha256(TEXT)


def test_non_text_files_in_raw_are_ignored(tmp_path: Path) -> None:
    add_source(tmp_path, "doc")
    (tmp_path / "raw" / "doc.pdf").write_bytes(b"%PDF-1.4 original download")
    assert len(load_corpus(tmp_path)) == 1


# --- Corrupted documents ----------------------------------------------------------


def test_rejects_text_that_does_not_match_expected_hash(tmp_path: Path) -> None:
    add_source(tmp_path, "doc", TEXT + "tampered", record(expected_sha256=reference_sha256(TEXT)))
    [problem] = problems_of(tmp_path)
    assert "expects" in problem and "doc.txt" in problem


def test_rejects_binary_file_with_nul_bytes(tmp_path: Path) -> None:
    add_source(tmp_path, "doc", b"PK\x03\x04\x00\x00binary zip")
    [problem] = problems_of(tmp_path)
    assert "NUL" in problem


def test_rejects_empty_text_file(tmp_path: Path) -> None:
    add_source(tmp_path, "doc", b"")
    [problem] = problems_of(tmp_path)
    assert "text must not be empty" in problem


def test_rejects_malformed_json_record(tmp_path: Path) -> None:
    add_source(tmp_path, "doc", raw_meta='{"title": "Unclosed"')
    [problem] = problems_of(tmp_path)
    assert "invalid provenance record" in problem


def test_rejects_malformed_expected_hash(tmp_path: Path) -> None:
    add_source(tmp_path, "doc", TEXT, record(expected_sha256="ABC123"))
    [problem] = problems_of(tmp_path)
    assert "expected_sha256" in problem


# --- Missing metadata ---------------------------------------------------------------


@pytest.mark.parametrize(
    "field", ["title", "source_name", "source_uri", "source_type", "retrieved_at", "rights"]
)
def test_rejects_record_missing_required_field(tmp_path: Path, field: str) -> None:
    meta = record()
    del meta[field]
    add_source(tmp_path, "doc", TEXT, meta)
    [problem] = problems_of(tmp_path)
    assert field in problem


@pytest.mark.parametrize("field", ["published", "authors"])
def test_unknown_values_must_be_explicit(tmp_path: Path, field: str) -> None:
    meta = record()
    del meta[field]  # omitted, rather than null / []
    add_source(tmp_path, "doc", TEXT, meta)
    [problem] = problems_of(tmp_path)
    assert field in problem


def test_rejects_text_file_without_provenance_record(tmp_path: Path) -> None:
    add_source(tmp_path, "doc")
    (tmp_path / "raw" / "orphan.txt").write_text("No record for this one.", encoding="utf-8")
    [problem] = problems_of(tmp_path)
    assert "orphan.txt" in problem and "no provenance record" in problem


def test_rejects_record_whose_text_is_missing(tmp_path: Path) -> None:
    add_source(tmp_path, "doc", text=None)
    [problem] = problems_of(tmp_path)
    assert "source text missing" in problem and "https://example.org/source" in problem


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"retrieved_at": "2026-10-30T12:00:00"}, "timezone-aware"),
        ({"published": "2027-01-01"}, "after retrieved_at"),
        ({"published": "July 2004"}, "YYYY"),
        ({"source_type": "reliable"}, "source_type"),
        ({"credibility": 0.9}, "credibility"),  # unknown fields are rejected, not ignored
    ],
)
def test_rejects_invalid_metadata_values(
    tmp_path: Path, override: dict[str, Any], expected: str
) -> None:
    add_source(tmp_path, "doc", TEXT, record(**override))
    [problem] = problems_of(tmp_path)
    assert expected in problem


def test_rejects_invalid_document_id_from_file_name(tmp_path: Path) -> None:
    add_source(tmp_path, "bad name")
    [problem] = problems_of(tmp_path)
    assert "id must match" in problem


def test_missing_sources_directory(tmp_path: Path) -> None:
    [problem] = problems_of(tmp_path)
    assert "sources directory not found" in problem


# --- Encoding errors ----------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        "Caf\xe9 report".encode("latin-1"),
        "UTF-16 text".encode("utf-16"),
    ],
)
def test_rejects_non_utf8_text(tmp_path: Path, data: bytes) -> None:
    add_source(tmp_path, "doc", data)
    [problem] = problems_of(tmp_path)
    assert "not valid UTF-8" in problem and "doc.txt" in problem


# --- Duplicates ---------------------------------------------------------------------


def test_rejects_exact_duplicate_documents(tmp_path: Path) -> None:
    add_source(tmp_path, "copy-a")
    add_source(tmp_path, "copy-b")
    [problem] = problems_of(tmp_path)
    assert "duplicate content" in problem and "copy-a" in problem and "copy-b" in problem


def test_detects_duplicates_that_differ_only_in_encoding_noise(tmp_path: Path) -> None:
    # Same visible text: CRLF + decomposed accents vs LF + composed accents + BOM.
    text = "Café findings.\nSecond line.\n"
    add_source(tmp_path, "nfc-lf", "﻿" + text)
    add_source(tmp_path, "nfd-crlf", unicodedata.normalize("NFD", text).replace("\n", "\r\n"))
    [problem] = problems_of(tmp_path)
    assert "duplicate content" in problem


# --- Error reporting ----------------------------------------------------------------


def test_reports_every_problem_at_once(tmp_path: Path) -> None:
    add_source(tmp_path, "good")
    add_source(tmp_path, "bad-encoding", "Caf\xe9".encode("latin-1"))
    add_source(tmp_path, "no-text", text=None)
    add_source(tmp_path, "bad-meta", "Fine text.", record(source_type="rumour"))

    problems = problems_of(tmp_path)

    assert len(problems) == 3
    assert not any("good" in p for p in problems)
