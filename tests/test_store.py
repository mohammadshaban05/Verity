"""Snapshot persistence: round trips, byte-level reproducibility, and corruption detection."""

import hashlib
import json
from pathlib import Path

import pytest

from factories import make_doc
from verity.ingest import MIN_FILL_RATIO
from verity.models import Document
from verity.normalize import NORMALIZATION_VERSION
from verity.store import (
    DOCUMENTS_FILE,
    MANIFEST_FILE,
    PASSAGES_FILE,
    Snapshot,
    SnapshotError,
    build_snapshot,
    check_reproducible,
    load_snapshot,
    save_snapshot,
)

BODY = "\n\n".join(
    " ".join(f"Paragraph {p} sentence {s} records a finding." for s in range(8)) for p in range(6)
)


def sample_documents() -> list[Document]:
    return [
        make_doc(BODY, doc_id="report-b"),
        # Characters that a careless line-based reader would split on.
        make_doc("Page one.\fPage two. Same line? \x85 " + BODY[:500], doc_id="report-a"),
    ]


def saved_snapshot(tmp_path: Path) -> tuple[Snapshot, Path]:
    snapshot = build_snapshot(sample_documents(), max_chars=200, overlap=40)
    out = tmp_path / "snap"
    save_snapshot(snapshot, out)
    return snapshot, out


def rewrite_with_valid_manifest(out: Path, name: str, payload: bytes) -> None:
    """Simulate a consistent tamper: change a data file and update its manifest hash."""
    (out / name).write_bytes(payload)
    manifest = json.loads((out / MANIFEST_FILE).read_text())
    manifest["files"][name] = hashlib.sha256(payload).hexdigest()
    (out / MANIFEST_FILE).write_text(json.dumps(manifest))


# --- Round trip and reproducibility ------------------------------------------------


def test_round_trip_preserves_everything(tmp_path: Path) -> None:
    snapshot, out = saved_snapshot(tmp_path)
    assert load_snapshot(out) == snapshot


def test_documents_are_stored_in_canonical_order(tmp_path: Path) -> None:
    snapshot, out = saved_snapshot(tmp_path)
    assert [d.id for d in snapshot.documents] == ["report-a", "report-b"]
    first_passage_docs = [json.loads(line)["doc_id"] for line in (out / PASSAGES_FILE).open()]
    assert first_passage_docs == sorted(first_passage_docs)


def test_same_input_gives_byte_identical_files(tmp_path: Path) -> None:
    for name in ("one", "two"):
        save_snapshot(build_snapshot(sample_documents(), 200, 40), tmp_path / name)
    for file in (DOCUMENTS_FILE, PASSAGES_FILE, MANIFEST_FILE):
        assert (tmp_path / "one" / file).read_bytes() == (tmp_path / "two" / file).read_bytes()


def test_input_order_does_not_matter(tmp_path: Path) -> None:
    docs = sample_documents()
    save_snapshot(build_snapshot(docs, 200, 40), tmp_path / "fwd")
    save_snapshot(build_snapshot(reversed(docs), 200, 40), tmp_path / "rev")
    assert (tmp_path / "fwd" / MANIFEST_FILE).read_bytes() == (
        tmp_path / "rev" / MANIFEST_FILE
    ).read_bytes()


def test_manifest_records_settings_and_counts(tmp_path: Path) -> None:
    snapshot, out = saved_snapshot(tmp_path)
    manifest = json.loads((out / MANIFEST_FILE).read_text())
    assert manifest["normalization"] == NORMALIZATION_VERSION
    assert manifest["chunking"] == {
        "max_chars": 200,
        "overlap": 40,
        "min_fill_ratio": MIN_FILL_RATIO,
    }
    assert manifest["document_count"] == 2
    assert manifest["passage_count"] == len(snapshot.passages)
    assert "created" not in json.dumps(manifest)  # no timestamps: keeps output byte-stable


def test_reloaded_snapshot_reproduces_under_current_chunker(tmp_path: Path) -> None:
    _, out = saved_snapshot(tmp_path)
    check_reproducible(load_snapshot(out))


def test_check_reproducible_detects_different_chunking() -> None:
    snapshot = build_snapshot(sample_documents(), 200, 40)
    altered = Snapshot(
        documents=snapshot.documents,
        passages=snapshot.passages[:-1],
        chunking=snapshot.chunking,
    )
    with pytest.raises(SnapshotError, match="different passages"):
        check_reproducible(altered)


def test_default_settings_match_milestone_decision() -> None:
    params = build_snapshot(sample_documents()).chunking
    assert (params.max_chars, params.overlap, params.min_fill_ratio) == (1000, 200, 0.5)


# --- Write safety ------------------------------------------------------------------


def test_refuses_to_overwrite_non_empty_directory(tmp_path: Path) -> None:
    snapshot, out = saved_snapshot(tmp_path)
    with pytest.raises(SnapshotError, match="not empty"):
        save_snapshot(snapshot, out)
    save_snapshot(snapshot, out, overwrite=True)
    assert load_snapshot(out) == snapshot


def test_rejects_duplicate_document_ids() -> None:
    with pytest.raises(SnapshotError, match="duplicate document ids"):
        build_snapshot([make_doc("One."), make_doc("Two.")])


# --- Corruption detection ----------------------------------------------------------


def test_detects_edited_byte_in_documents_file(tmp_path: Path) -> None:
    _, out = saved_snapshot(tmp_path)
    data = (out / DOCUMENTS_FILE).read_bytes()
    (out / DOCUMENTS_FILE).write_bytes(data.replace(b"finding", b"findinG", 1))
    with pytest.raises(SnapshotError, match="does not match the manifest hash"):
        load_snapshot(out)


def test_detects_truncated_passages_file(tmp_path: Path) -> None:
    _, out = saved_snapshot(tmp_path)
    data = (out / PASSAGES_FILE).read_bytes()
    (out / PASSAGES_FILE).write_bytes(data[: len(data) // 2])
    with pytest.raises(SnapshotError, match="does not match the manifest hash"):
        load_snapshot(out)


@pytest.mark.parametrize("missing", [MANIFEST_FILE, DOCUMENTS_FILE, PASSAGES_FILE])
def test_detects_missing_files(tmp_path: Path, missing: str) -> None:
    _, out = saved_snapshot(tmp_path)
    (out / missing).unlink()
    with pytest.raises(SnapshotError, match="not found|missing"):
        load_snapshot(out)


def test_detects_document_text_edited_with_consistent_hashes(tmp_path: Path) -> None:
    # Edit a document's text and fix both its sha256 and the manifest hash.
    # The data and file hashes now agree, but stored passages no longer slice the text.
    _, out = saved_snapshot(tmp_path)
    lines = (out / DOCUMENTS_FILE).read_bytes().splitlines(keepends=True)
    doc = json.loads(lines[1])
    doc["text"] = doc["text"].replace("finding", "rumour")
    doc["sha256"] = hashlib.sha256(doc["text"].encode("utf-8")).hexdigest()
    lines[1] = (json.dumps(doc, ensure_ascii=False) + "\n").encode("utf-8")
    rewrite_with_valid_manifest(out, DOCUMENTS_FILE, b"".join(lines))
    with pytest.raises(SnapshotError, match="does not match its document span"):
        load_snapshot(out)


def test_detects_passage_text_edited_with_consistent_manifest(tmp_path: Path) -> None:
    _, out = saved_snapshot(tmp_path)
    lines = (out / PASSAGES_FILE).read_bytes().splitlines(keepends=True)
    passage = json.loads(lines[0])
    passage["text"] = passage["text"].replace("records", "invents")  # same length
    lines[0] = (json.dumps(passage) + "\n").encode("utf-8")
    rewrite_with_valid_manifest(out, PASSAGES_FILE, b"".join(lines))
    with pytest.raises(SnapshotError, match="does not match its document span"):
        load_snapshot(out)


def test_detects_document_whose_hash_no_longer_matches_text(tmp_path: Path) -> None:
    _, out = saved_snapshot(tmp_path)
    lines = (out / DOCUMENTS_FILE).read_bytes().splitlines(keepends=True)
    doc = json.loads(lines[0])
    doc["text"] = doc["text"] + " extra"
    lines[0] = (json.dumps(doc, ensure_ascii=False) + "\n").encode("utf-8")
    rewrite_with_valid_manifest(out, DOCUMENTS_FILE, b"".join(lines))
    with pytest.raises(SnapshotError, match="sha256 does not match text"):
        load_snapshot(out)


def test_detects_forged_passage_id(tmp_path: Path) -> None:
    _, out = saved_snapshot(tmp_path)
    lines = (out / PASSAGES_FILE).read_bytes().splitlines(keepends=True)
    passage = json.loads(lines[0])
    passage["id"] = "report-a@000000000000:0-10"
    lines[0] = (json.dumps(passage) + "\n").encode("utf-8")
    rewrite_with_valid_manifest(out, PASSAGES_FILE, b"".join(lines))
    with pytest.raises(SnapshotError, match="canonical id"):
        load_snapshot(out)


def test_rejects_unsupported_format_version(tmp_path: Path) -> None:
    _, out = saved_snapshot(tmp_path)
    manifest = json.loads((out / MANIFEST_FILE).read_text())
    manifest["format_version"] = 99
    (out / MANIFEST_FILE).write_text(json.dumps(manifest))
    with pytest.raises(SnapshotError, match="unsupported snapshot format"):
        load_snapshot(out)
