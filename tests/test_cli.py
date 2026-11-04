"""End-to-end CLI: ingest, verify, search and evaluate."""

import json
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


def test_search_and_evaluate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    corpus, out = tmp_path / "corpus", tmp_path / "snap"
    add_source(corpus, "fires", "Fires on several floors weakened the steel beams. " * 3)
    add_source(corpus, "radios", "The radios failed inside the tall building. " * 3)
    assert main(["ingest", "--corpus", str(corpus), "--out", str(out)]) == 0
    capsys.readouterr()

    assert main(["search", "steel beams", "--snapshot", str(out)]) == 0
    assert "fires@" in capsys.readouterr().out
    assert main(["search", "thermite", "--snapshot", str(out)]) == 0
    assert "no passage matches" in capsys.readouterr().out

    gold = tmp_path / "gold.jsonl"
    record = {
        "id": "c1",
        "claim": "Radios failed in the building.",
        "label": "supported",
        "topic": "t",
        "phrasing": "lexical",
        "evidence": [{"doc_id": "radios", "quote": "radios failed", "stance": "supports"}],
    }
    gold.write_text(json.dumps(record) + "\n", encoding="utf-8")
    assert main(["evaluate", "--gold", str(gold), "--snapshot", str(out)]) == 0
    assert "1 claims (1 answerable)" in capsys.readouterr().out

    record["evidence"][0]["quote"] = "not in the corpus"
    gold.write_text(json.dumps(record) + "\n", encoding="utf-8")
    assert main(["evaluate", "--gold", str(gold), "--snapshot", str(out)]) == 1
    assert "quote not found" in capsys.readouterr().err
