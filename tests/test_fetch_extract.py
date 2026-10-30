"""HTML article extraction used by scripts/fetch_corpus.py."""

import importlib.util
from pathlib import Path

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
    text = fetch_corpus.extract_article_text(page("<p>Fire &amp; steel — “towers’ collapse”</p>"))
    assert text == "Fire & steel — “towers’ collapse”\n"
