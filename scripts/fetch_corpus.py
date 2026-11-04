"""Download source texts listed in data/corpus/sources/ into data/corpus/raw/.

Usage:
    uv run --group corpus python scripts/fetch_corpus.py [--only ID] [--force] [--accept]

For each provenance record it does the following:
  - downloads ``source_uri`` and keeps the original bytes (raw/<id>.pdf, .html or
    .json) so the text extraction can be audited
  - extracts the text to raw/<id>.txt (PDF pages are separated by a form feed)
  - on first fetch, writes ``retrieved_at`` and ``expected_sha256`` into the record
  - on later fetches, reports whether the result reproduces the recorded hash. With
    --accept it records the new version instead.

Supported sources:
  - a pinned Wikipedia revision, ``https://<lang>.wikipedia.org/w/index.php?oldid=N``,
    fetched as MediaWiki parser output and reduced to the article prose
  - a SciFact abstract, ``<SciFact release tarball URL>#doc_id=N``: title, blank
    line, then the abstract sentences joined by spaces
  - any other URL serving a PDF, or HTML with an ``itemprop="articleBody"`` element

The extracted texts (raw/*.txt) are committed when the source's license allows
redistribution (ADR-013). Original downloads are gitignored.
"""

import argparse
import io
import json
import sys
import tarfile
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

from verity.models import sha256_hex
from verity.normalize import normalize_bytes

USER_AGENT = "Mozilla/5.0 (compatible; Verity research corpus builder)"
# Wikimedia asks API clients to identify themselves with a contact URL.
WIKIMEDIA_USER_AGENT = "VerityCorpusBuilder/0.1 (https://github.com/mohammadshaban05/Verity)"
_TARBALLS: dict[str, dict[int, dict]] = {}  # SciFact corpus per release URL, per run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=Path("data/corpus"))
    parser.add_argument("--only", help="fetch a single document id")
    parser.add_argument("--force", action="store_true", help="re-download existing texts")
    parser.add_argument("--accept", action="store_true", help="record a changed hash")
    args = parser.parse_args()

    raw_dir = args.corpus / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for record_path in sorted((args.corpus / "sources").glob("*.json")):
        doc_id = record_path.stem
        if args.only and doc_id != args.only:
            continue
        text_path = raw_dir / f"{doc_id}.txt"
        if text_path.exists() and not args.force:
            print(f"skip   {doc_id} (already fetched; use --force to re-download)")
            continue
        record = json.loads(record_path.read_text(encoding="utf-8"))
        try:
            failures += not _fetch_one(doc_id, record, record_path, raw_dir, args.accept)
        except Exception as exc:  # report and continue with the other sources
            print(f"FAIL   {doc_id}: {exc}")
            failures += 1
    return 1 if failures else 0


def _fetch_one(doc_id: str, record: dict, record_path: Path, raw_dir: Path, accept: bool) -> bool:
    uri = urllib.parse.urlsplit(record["source_uri"])
    oldid = urllib.parse.parse_qs(uri.query).get("oldid")
    if uri.netloc.endswith(".wikipedia.org") and oldid:
        html = fetch_wikipedia_revision(uri.netloc, int(oldid[0]))
        (raw_dir / f"{doc_id}.html").write_text(html, encoding="utf-8")
        text = extract_wikipedia_text(html)
    elif uri.path.endswith("data.tar.gz") and uri.fragment.startswith("doc_id="):
        abstract = fetch_scifact_abstract(record["source_uri"])
        (raw_dir / f"{doc_id}.json").write_text(json.dumps(abstract) + "\n", encoding="utf-8")
        text = scifact_text(abstract)
    else:
        text = _fetch_url(doc_id, record["source_uri"], raw_dir)

    data = text.encode("utf-8")
    (raw_dir / f"{doc_id}.txt").write_bytes(data)
    digest = sha256_hex(normalize_bytes(data))

    expected = record.get("expected_sha256")
    if expected == digest:
        print(f"ok     {doc_id}: reproduced recorded hash {digest[:12]}")
        return True
    if expected is not None and not accept:
        print(f"DRIFT  {doc_id}: got {digest[:12]}, record expects {expected[:12]} (--accept)")
        return False
    record["retrieved_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    record["expected_sha256"] = digest
    record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(f"new    {doc_id}: {len(text):,} chars, sha256 {digest[:12]} recorded")
    return True


def _fetch_url(doc_id: str, url: str, raw_dir: Path) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = response.read()
        content_type = response.headers.get_content_type()
    if content_type == "application/pdf" or payload.startswith(b"%PDF"):
        (raw_dir / f"{doc_id}.pdf").write_bytes(payload)
        return extract_pdf_text(payload)
    if content_type == "text/html":
        (raw_dir / f"{doc_id}.html").write_bytes(payload)
        return extract_article_text(payload.decode("utf-8"))
    raise ValueError(f"unsupported content type {content_type!r}")


def fetch_wikipedia_revision(host: str, revid: int) -> str:
    """Parser output (HTML) of one pinned revision. Templates are expanded with
    their current versions, so a re-fetch can drift even for a fixed revision;
    the recorded hash detects that."""
    query = urllib.parse.urlencode(
        {
            "action": "parse",
            "oldid": revid,
            "prop": "text",
            "format": "json",
            "formatversion": 2,
            "disableeditsection": 1,
            "disablelimitreport": 1,
        }
    )
    request = urllib.request.Request(
        f"https://{host}/w/api.php?{query}", headers={"User-Agent": WIKIMEDIA_USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)["parse"]["text"]


def fetch_scifact_abstract(uri: str) -> dict:
    url, _, fragment = uri.partition("#")
    if url not in _TARBALLS:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=300) as response:
            archive = tarfile.open(fileobj=io.BytesIO(response.read()), mode="r:gz")
        lines = archive.extractfile("data/corpus.jsonl").read().decode("utf-8").splitlines()
        _TARBALLS[url] = {d["doc_id"]: d for d in (json.loads(line) for line in lines if line)}
    return _TARBALLS[url][int(fragment.removeprefix("doc_id="))]


def scifact_text(abstract: dict) -> str:
    sentences = " ".join(" ".join(s.split()) for s in abstract["abstract"])
    return f"{' '.join(abstract['title'].split())}\n\n{sentences}\n"


def extract_pdf_text(payload: bytes) -> str:
    from pypdf import PdfReader  # "corpus" dependency group; imported lazily

    reader = PdfReader(io.BytesIO(payload))
    return "\f".join(page.extract_text() or "" for page in reader.pages)


class _ArticleExtractor(HTMLParser):
    """Collect block-level text inside the article body (itemprop="articleBody").

    Whitespace inside a block is collapsed, as a browser would render it.
    Page furniture inside the body is dropped:
      - script/style/figure/aside/button/svg/noscript elements
      - labelled lists (<ul aria-label=...>), e.g. topic tags
      - cross-promotion paragraphs starting with "Read more:"
    """

    BLOCKS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote"}
    SKIP = {"script", "style", "figure", "aside", "button", "svg", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        # Each region (the article container, a skipped element) ends when the
        # count of open tags with its name returns to zero. Void tags such as <br>
        # never match, so they can't unbalance the count.
        self.container_tag: str | None = None
        self.container_open = 0
        self.skip_tag: str | None = None
        self.skip_open = 0
        self.finished = False
        self.blocks: list[str] = []
        self.current: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.finished:
            return
        if self.container_tag is None:
            if ("itemprop", "articleBody") in attrs:
                self.container_tag, self.container_open = tag, 1
            return
        if tag == self.container_tag:
            self.container_open += 1
        if self.skip_tag is not None:
            if tag == self.skip_tag:
                self.skip_open += 1
        elif tag in self.SKIP or (tag in ("ul", "ol") and dict(attrs).get("aria-label")):
            self.skip_tag, self.skip_open = tag, 1
        elif tag in self.BLOCKS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if self.finished or self.container_tag is None:
            return
        if self.skip_tag is not None:
            if tag == self.skip_tag:
                self.skip_open -= 1
                if self.skip_open == 0:
                    self.skip_tag = None
        elif tag in self.BLOCKS:
            self._flush()
        if tag == self.container_tag:
            self.container_open -= 1
            if self.container_open == 0:
                self._flush()
                self.finished = True

    def handle_data(self, data: str) -> None:
        if self.container_tag is not None and not self.finished and self.skip_tag is None:
            self.current.append(data)

    def _flush(self) -> None:
        block = " ".join("".join(self.current).split())
        if block and not block.startswith("Read more:"):
            self.blocks.append(block)
        self.current = []


def extract_article_text(html: str) -> str:
    extractor = _ArticleExtractor()
    extractor.feed(html)
    extractor.close()
    if not extractor.blocks:
        raise ValueError('no itemprop="articleBody" content found')
    return "\n\n".join(extractor.blocks) + "\n"


class _WikipediaExtractor(HTMLParser):
    """Collect the prose of a Wikipedia article from MediaWiki parser output.

    Kept: paragraphs, headings, list items and block quotes, in document order,
    with whitespace collapsed inside each block.
    Dropped:
      - tables (infoboxes, navboxes, data tables), figures and image captions
      - hatnotes, maintenance banners, the table of contents
      - citation markers ("[12]") and inline maintenance tags ("[citation needed]")
      - math markup
      - everything from the first end-matter heading on ("See also",
        "References", "External links" and similar)
    """

    BLOCKS = {"p", "h2", "h3", "h4", "h5", "h6", "li", "dd", "dt", "blockquote"}
    SKIP_TAGS = {"style", "script", "table", "figure", "link", "meta"}
    SKIP_CLASSES = {
        "ambox", "gallery", "hatnote", "infobox", "metadata", "mw-editsection",
        "mw-empty-elt", "mwe-math-element", "navbox", "navigation-not-searchable",
        "noprint", "portalbox", "reference", "reflist", "references", "shortdescription",
        "sidebar", "side-box", "thumb", "toc",
    }  # fmt: skip
    END_SECTIONS = {
        "bibliography", "citations", "external links", "explanatory notes", "footnotes",
        "further reading", "notes", "notes and references", "references", "see also",
        "sources", "works cited",
    }  # fmt: skip

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_tag: str | None = None
        self.skip_open = 0
        self.finished = False
        self.blocks: list[str] = []
        self.current: list[str] = []
        self.current_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.finished:
            return
        if self.skip_tag is not None:
            if tag == self.skip_tag:
                self.skip_open += 1
            return
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if (
            tag in self.SKIP_TAGS
            or classes & self.SKIP_CLASSES
            or attributes.get("role") == "note"
            or (tag == "div" and "thumbinner" in classes)
        ):
            self.skip_tag, self.skip_open = tag, 1
        elif tag in self.BLOCKS:
            self._flush()
            self.current_tag = tag

    def handle_endtag(self, tag: str) -> None:
        if self.finished:
            return
        if self.skip_tag is not None:
            if tag == self.skip_tag:
                self.skip_open -= 1
                if self.skip_open == 0:
                    self.skip_tag = None
        elif tag in self.BLOCKS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self.finished and self.skip_tag is None:
            self.current.append(data)

    def _flush(self) -> None:
        block = " ".join("".join(self.current).split())
        tag, self.current, self.current_tag = self.current_tag, [], None
        if not block:
            return
        if tag == "h2" and block.casefold() in self.END_SECTIONS:
            self.finished = True
            return
        self.blocks.append(block)


def extract_wikipedia_text(html: str) -> str:
    extractor = _WikipediaExtractor()
    extractor.feed(html)
    extractor.close()
    extractor._flush()
    if not extractor.blocks:
        raise ValueError("no article prose found in the Wikipedia parser output")
    return "\n\n".join(extractor.blocks) + "\n"


if __name__ == "__main__":
    sys.exit(main())
