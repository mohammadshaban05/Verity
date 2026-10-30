"""Save and load reproducible corpus snapshots (ADR-009).

A snapshot directory contains:

    documents.jsonl   one Document per line, sorted by id
    passages.jsonl    one Passage per line, sorted by (doc_id, start)
    manifest.json     format version, normalization and chunking settings, counts,
                      and the sha256 of each data file. Written last.

Writing the same documents with the same settings produces byte-identical
files. The manifest contains no timestamps, which is why. Loading checks
integrity in two layers:

1. File hashes. Any change to a data file, including truncation, is detected.
2. Meaning. Every Document re-checks its text hash; every Passage must slice
   its document exactly and carry its canonical ID.
"""

import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

import verity
from verity.ingest import MIN_FILL_RATIO, chunk_document, passage_id
from verity.models import Document, Passage
from verity.normalize import NORMALIZATION_VERSION

SNAPSHOT_FORMAT_VERSION = 1
DOCUMENTS_FILE = "documents.jsonl"
PASSAGES_FILE = "passages.jsonl"
MANIFEST_FILE = "manifest.json"


class SnapshotError(ValueError):
    """A snapshot can't be built, written or trusted."""


class ChunkingParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_chars: int
    overlap: int
    min_fill_ratio: float


class SnapshotManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    format_version: int
    verity_version: str
    normalization: str
    chunking: ChunkingParams
    document_count: int
    passage_count: int
    files: dict[str, str]  # file name -> sha256 of its bytes


@dataclass(frozen=True)
class Snapshot:
    documents: tuple[Document, ...]
    passages: tuple[Passage, ...]
    chunking: ChunkingParams
    normalization: str = NORMALIZATION_VERSION


def build_snapshot(
    documents: Iterable[Document], max_chars: int = 1000, overlap: int = 200
) -> Snapshot:
    """Chunk documents into a snapshot with a canonical order."""
    docs = sorted(documents, key=lambda d: d.id)
    ids = [d.id for d in docs]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise SnapshotError(f"duplicate document ids: {duplicates}")
    passages = [p for doc in docs for p in chunk_document(doc, max_chars, overlap)]
    return Snapshot(
        documents=tuple(docs),
        passages=tuple(passages),
        chunking=ChunkingParams(
            max_chars=max_chars, overlap=overlap, min_fill_ratio=MIN_FILL_RATIO
        ),
    )


def save_snapshot(snapshot: Snapshot, out_dir: Path, *, overwrite: bool = False) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    if any(out_dir.iterdir()) and not overwrite:
        raise SnapshotError(f"{out_dir} is not empty; pass overwrite=True to replace it")
    # Remove the old manifest first. If writing is interrupted, the directory is
    # then obviously incomplete, rather than a mix of old and new files.
    (out_dir / MANIFEST_FILE).unlink(missing_ok=True)

    data = {
        DOCUMENTS_FILE: _to_jsonl(snapshot.documents),
        PASSAGES_FILE: _to_jsonl(snapshot.passages),
    }
    for name, payload in data.items():
        _atomic_write(out_dir / name, payload)

    manifest = SnapshotManifest(
        format_version=SNAPSHOT_FORMAT_VERSION,
        verity_version=verity.__version__,
        normalization=snapshot.normalization,
        chunking=snapshot.chunking,
        document_count=len(snapshot.documents),
        passage_count=len(snapshot.passages),
        files={name: hashlib.sha256(payload).hexdigest() for name, payload in data.items()},
    )
    manifest_json = json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True)
    _atomic_write(out_dir / MANIFEST_FILE, (manifest_json + "\n").encode("utf-8"))


def load_snapshot(snapshot_dir: Path) -> Snapshot:
    manifest_path = snapshot_dir / MANIFEST_FILE
    if not manifest_path.is_file():
        raise SnapshotError(f"{manifest_path} not found (incomplete or not a snapshot)")
    try:
        manifest = SnapshotManifest.model_validate_json(manifest_path.read_bytes())
    except ValidationError as exc:
        raise SnapshotError(f"{manifest_path}: invalid manifest: {exc}") from exc
    if manifest.format_version != SNAPSHOT_FORMAT_VERSION:
        raise SnapshotError(f"unsupported snapshot format version {manifest.format_version}")
    if set(manifest.files) != {DOCUMENTS_FILE, PASSAGES_FILE}:
        raise SnapshotError(f"manifest lists unexpected files: {sorted(manifest.files)}")

    payloads: dict[str, bytes] = {}
    for name, expected in manifest.files.items():
        path = snapshot_dir / name
        if not path.is_file():
            raise SnapshotError(f"{path} is missing")
        payloads[name] = path.read_bytes()
        if hashlib.sha256(payloads[name]).hexdigest() != expected:
            raise SnapshotError(f"{path} does not match the manifest hash (corrupted or edited)")

    documents = _from_jsonl(payloads[DOCUMENTS_FILE], Document, DOCUMENTS_FILE)
    passages = _from_jsonl(payloads[PASSAGES_FILE], Passage, PASSAGES_FILE)
    _check_consistency(manifest, documents, passages)
    return Snapshot(
        documents=tuple(documents),
        passages=tuple(passages),
        chunking=manifest.chunking,
        normalization=manifest.normalization,
    )


def check_reproducible(snapshot: Snapshot) -> None:
    """Re-chunk the snapshot's documents with its recorded settings and require
    identical passages. This detects chunker changes that would alter results."""
    params = snapshot.chunking
    if params.min_fill_ratio != MIN_FILL_RATIO:
        raise SnapshotError(
            f"snapshot used min_fill_ratio={params.min_fill_ratio}, code uses {MIN_FILL_RATIO}"
        )
    rebuilt = build_snapshot(snapshot.documents, params.max_chars, params.overlap)
    if rebuilt.passages != snapshot.passages:
        raise SnapshotError("re-chunking with the recorded settings gives different passages")


def _check_consistency(
    manifest: SnapshotManifest, documents: list[Document], passages: list[Passage]
) -> None:
    if len(documents) != manifest.document_count or len(passages) != manifest.passage_count:
        raise SnapshotError("document or passage count differs from the manifest")
    doc_ids = [d.id for d in documents]
    if doc_ids != sorted(set(doc_ids)):
        raise SnapshotError("document ids are duplicated or out of order")
    docs_by_id = {d.id: d for d in documents}

    seen_ids: set[str] = set()
    previous_key: tuple[str, int] | None = None
    for p in passages:
        doc = docs_by_id.get(p.doc_id)
        if doc is None:
            raise SnapshotError(f"passage {p.id} refers to unknown document {p.doc_id!r}")
        if doc.text[p.start : p.end] != p.text:
            raise SnapshotError(f"passage {p.id} text does not match its document span")
        if p.id != passage_id(doc, p.start, p.end):
            raise SnapshotError(f"passage {p.id} does not have its canonical id")
        if p.id in seen_ids:
            raise SnapshotError(f"duplicate passage id {p.id}")
        seen_ids.add(p.id)
        key = (p.doc_id, p.start)
        if previous_key is not None and key <= previous_key:
            raise SnapshotError(f"passage {p.id} is out of order")
        previous_key = key


def _to_jsonl(models: Iterable[BaseModel]) -> bytes:
    return b"".join(m.model_dump_json().encode("utf-8") + b"\n" for m in models)


def _from_jsonl[M: BaseModel](payload: bytes, model: type[M], name: str) -> list[M]:
    items = []
    # bytes.splitlines splits only on \n and \r. str.splitlines would also split on
    # U+2028, NEL and form feed. Those can appear in document text, though JSON
    # escapes most of them.
    for line_no, line in enumerate(payload.splitlines(), start=1):
        try:
            items.append(model.model_validate_json(line))
        except ValidationError as exc:
            raise SnapshotError(f"{name} line {line_no}: {exc}") from exc
    return items


def _atomic_write(path: Path, payload: bytes) -> None:
    # Write to a temporary file and then rename it over the target. A reader
    # sees either the old file or the new one, never a half-written file.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, path)
