"""HTML article extraction used by scripts/fetch_corpus.py."""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "fetch_corpus", Path(__file__).parents[1] / "scripts" / "fetch_corpus.py"
)
assert _spec and _spec.loader
fetch_corpus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_corpus)


def page(body: str) -> str:
    return (
        "<html><body><nav><p>Site menu</p></nav>"
        f'<div class="wrap"><div itemprop="articleBody">{body}</div></div>'
        "<div><p>Comments section</p></div><footer><p>Footer</p></footer></body></html>"
    )


def test_extracts_only_article_blocks_with_collapsed_whitespace() -> None:
    html = page("<h2>Heading</h2><p>First   para\n with <em>inline</em> text.</p><p>Second.</p>")
    text = fetch_corpus.extract_article_text(html)
    assert text == "Heading\n\nFirst para with inline text.\n\nSecond.\n"


def test_content_after_the_article_body_is_not_captured() -> None:
    text = fetch_corpus.extract_article_text(page("<div><p>Inside.</p></div>"))
    assert "Comments" not in text and "Footer" not in text and "menu" not in text


def test_drops_topic_lists_promos_scripts_and_figures() -> None:
    body = (
        "<p>Real content.</p>"
        "<p><em><strong>Read more: <a href='#'>Other story</a></strong></em></p>"
        "<figure><img src='x.png'><figcaption>Caption</figcaption></figure>"
        "<script>var tracking = 1;</script>"
        "<ul aria-label='Topics'><li><a>Tag one</a></li><li><ul><li>Nested</li></ul></li></ul>"
        "<ul><li>A real list item.</li></ul>"
    )
    text = fetch_corpus.extract_article_text(page(body))
    assert text == "Real content.\n\nA real list item.\n"


def test_decodes_entities_and_keeps_typographic_characters() -> None:
    text = fetch_corpus.extract_article_text(page("<p>Salt &amp; pepper — “cooks’ choice”</p>"))
    assert text == "Salt & pepper — “cooks’ choice”\n"


# --- Wikipedia parser output ---------------------------------------------------------


def wiki(body: str) -> str:
    return f'<div class="mw-content-ltr mw-parser-output">{body}</div>'


def test_wikipedia_keeps_prose_and_drops_markers_tables_and_figures() -> None:
    html = wiki(
        '<div role="note" class="hatnote">For the city, see X.</div>'
        '<table class="infobox"><tr><td>Born 1466</td></tr></table>'
        '<p>The dodo<sup class="reference"><a>[1]</a></sup> was a bird'
        '<sup class="noprint Inline-Template"><i>[citation needed]</i></sup>.</p>'
        '<figure><img src="d.png"><figcaption>A dodo</figcaption></figure>'
        '<div class="mw-heading"><h2>Description'
        '<span class="mw-editsection">[edit]</span></h2></div>'
        "<ul><li>Grey   head</li><li>Yellow feet</li></ul>"
    )
    text = fetch_corpus.extract_wikipedia_text(html)
    assert text == "The dodo was a bird.\n\nDescription\n\nGrey head\n\nYellow feet\n"


def test_wikipedia_stops_at_the_first_end_matter_heading() -> None:
    html = wiki("<p>Body.</p><h2>See also</h2><ul><li>Other</li></ul><h2>History</h2><p>Late</p>")
    assert fetch_corpus.extract_wikipedia_text(html) == "Body.\n"


def test_wikipedia_end_matter_names_only_count_as_h2() -> None:
    html = wiki("<p>Body.</p><h3>Notes</h3><p>Still prose.</p>")
    assert fetch_corpus.extract_wikipedia_text(html) == "Body.\n\nNotes\n\nStill prose.\n"


def test_wikipedia_without_prose_is_an_error() -> None:
    with pytest.raises(ValueError, match="no article prose"):
        fetch_corpus.extract_wikipedia_text(wiki("<table><tr><td>only a table</td></tr></table>"))


# --- SciFact abstracts and source dispatch ----------------------------------------------


def test_scifact_text_is_title_blank_line_then_sentences() -> None:
    abstract = {"title": "A  study\n", "abstract": ["First sentence. ", "Second\n one."]}
    assert fetch_corpus.scifact_text(abstract) == "A study\n\nFirst sentence. Second one.\n"


def test_fetch_dispatches_on_source_uri_and_records_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        fetch_corpus,
        "fetch_wikipedia_revision",
        lambda host, revid: calls.append(("wiki", host, revid)) or wiki("<p>Wiki text.</p>"),
    )
    monkeypatch.setattr(
        fetch_corpus,
        "fetch_scifact_abstract",
        lambda uri: calls.append(("scifact", uri)) or {"title": "T", "abstract": ["S."]},
    )
    records = {
        "w": "https://simple.wikipedia.org/w/index.php?oldid=42",
        "s": "https://example.org/release/data.tar.gz#doc_id=7",
    }
    for doc_id, uri in records.items():
        record_path = tmp_path / f"{doc_id}.json"
        record = {"source_uri": uri}
        assert fetch_corpus._fetch_one(doc_id, record, record_path, tmp_path, accept=False)
        assert len(record["expected_sha256"]) == 64
    assert calls == [("wiki", "simple.wikipedia.org", 42), ("scifact", records["s"])]
    assert (tmp_path / "w.txt").read_text(encoding="utf-8") == "Wiki text.\n"
    assert (tmp_path / "s.txt").read_text(encoding="utf-8") == "T\n\nS.\n"
    assert (tmp_path / "w.html").exists() and (tmp_path / "s.json").exists()
