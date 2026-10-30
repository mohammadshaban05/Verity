"""Command-line entry point: ``python -m verity <command>``.

Commands:
    ingest   load a corpus directory, chunk it, and write a verified snapshot
    verify   check a snapshot's integrity and that re-chunking reproduces it
"""

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from verity.corpus import CorpusError, load_corpus
from verity.store import (
    Snapshot,
    SnapshotError,
    build_snapshot,
    check_reproducible,
    load_snapshot,
    save_snapshot,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m verity")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="build a snapshot from a corpus directory")
    ingest.add_argument("--corpus", type=Path, default=Path("data/corpus"))
    ingest.add_argument("--out", type=Path, default=Path("data/snapshots/current"))
    ingest.add_argument("--max-chars", type=int, default=1000)
    ingest.add_argument("--overlap", type=int, default=200)
    ingest.add_argument("--overwrite", action="store_true")

    verify = commands.add_parser("verify", help="verify an existing snapshot")
    verify.add_argument("snapshot", type=Path, nargs="?", default=Path("data/snapshots/current"))

    args = parser.parse_args(argv)
    try:
        if args.command == "ingest":
            documents = load_corpus(args.corpus)
            snapshot = build_snapshot(documents, args.max_chars, args.overlap)
            save_snapshot(snapshot, args.out, overwrite=args.overwrite)
            snapshot = load_snapshot(args.out)  # prove the written files read back cleanly
            print(f"Wrote {args.out}")
        else:
            snapshot = load_snapshot(args.snapshot)
            check_reproducible(snapshot)
            print(f"{args.snapshot}: integrity OK; re-chunking reproduces all passages")
    except (CorpusError, SnapshotError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _print_summary(snapshot)
    return 0


def _print_summary(snapshot: Snapshot) -> None:
    per_doc = Counter(p.doc_id for p in snapshot.passages)
    print(f"{'document':42} {'type':11} {'published':10} {'chars':>9} {'passages':>8}")
    for doc in snapshot.documents:
        print(
            f"{doc.id:42} {doc.source_type.value:11} {doc.published or 'unknown':10} "
            f"{len(doc.text):>9,} {per_doc[doc.id]:>8}"
        )
    params = snapshot.chunking
    print(
        f"{len(snapshot.documents)} documents, {len(snapshot.passages)} passages "
        f"(max_chars={params.max_chars}, overlap={params.overlap}, "
        f"min_fill_ratio={params.min_fill_ratio}, normalization={snapshot.normalization})"
    )


if __name__ == "__main__":
    sys.exit(main())
