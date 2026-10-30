"""End-to-end: corpus directory -> `python -m verity ingest` -> `verify`."""

from pathlib import Path

import pytest

from test_corpus import add_source
from verity.__main__ import main


def test_ingest_then_verify(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    corpus, out = tmp_path / "corpus", tmp_path / "snap"
    add_source(corpus, "doc-one", "First source text. " * 120)
    add_source(corpus, "doc-two", "Second source text. " * 30)

    assert main(["ingest", "--corpus", str(corpus), "--out", str(out)]) == 0
    assert "2 documents" in capsys.readouterr().out

    assert main(["verify", str(out)]) == 0
    assert "re-chunking reproduces all passages" in capsys.readouterr().out


def test_ingest_reports_corpus_problems(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    corpus = tmp_path / "corpus"
    add_source(corpus, "doc", "Caf\xe9".encode("latin-1"))

    assert main(["ingest", "--corpus", str(corpus), "--out", str(tmp_path / "snap")]) == 1
    assert "not valid UTF-8" in capsys.readouterr().err
    assert not (tmp_path / "snap").exists()
