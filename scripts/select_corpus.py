"""Write the provenance records of the seed corpus (data/corpus/sources/*.json).

Usage:
    uv run python scripts/select_corpus.py [--corpus data/corpus] [--scifact DIR]

This script records *which* documents are in the corpus and why. It writes
provenance only; ``scripts/fetch_corpus.py`` then downloads each text, records
its hash, and writes ``raw/<id>.txt``.

The corpus is deliberately small, multi-subject and redistributable:

* Wikipedia articles (CC BY-SA 4.0), each pinned to one revision ID:
  - FEVER pages: articles whose claims appear in the FEVER dev set, chosen to
    cover different subjects (history, geology, biology, music, literature,
    technology, geography, anatomy, astronomy).
  - WikiContradict pages: articles that the WikiContradict benchmark found to
    contradict themselves, pinned to a 2023/2024 revision in which both
    conflicting passages are present in the article prose.
  - Simple English Wikipedia pages on five of the FEVER subjects: separately
    written articles, so some facts have a second source, and one (Yandex's
    launch date) has a second source that disagrees.
* SciFact abstracts (ODC-By 1.0): the evidence and cited abstracts of a seeded,
  label-stratified random sample of SciFact dev claims, plus seeded random
  distractor abstracts from the rest of the SciFact corpus.

Selection is deterministic: the same SciFact release and seed give the same
records. Records that already exist keep their recorded hash and retrieval time.
"""

import argparse
import io
import json
import random
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path

SCIFACT_URL = "https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz"
USER_AGENT = "VerityCorpusBuilder/0.1 (https://github.com/mohammadshaban05/Verity)"

# (article title, revision id). FEVER pages are pinned to their revision at
# corpus creation (2026-11); WikiContradict pages to the revision that still
# contained both sides of the documented contradiction.
FEVER_PAGES = [
    ("Elizabeth of York", 1381204294),
    ("Cretaceous", 1383605539),
    ("Dodo", 1375347989),
    ("Philip Glass", 1382501805),
    ("Sancho Panza", 1379920596),
    ("Yandex", 1382077537),
    ("Hindu Kush", 1376768386),
    ("Heart", 1383668909),
    ("Near-Earth object", 1376698751),
]
SIMPLE_PAGES = [
    ("Yandex", 10458131),
    ("Near-Earth object", 10427113),
    ("Dodo", 11027682),
    ("Cretaceous", 10991469),
    ("Elizabeth of York", 10969547),
]
WIKICONTRADICT_PAGES = [
    ("Munsee language", 1204134377),
    ("Torpedo", 1210926479),
    ("CD19", 1199269744),
    ("Aedes albopictus", 1209117076),
    ("Chartreuse (liqueur)", 1194284821),
    ("Acne", 1206513250),
    ("Bremen", 1208767633),
    ("Loretto Chapel", 1191210227),
]

SEED = 20261103
SCIFACT_SAMPLE = {"SUPPORT": 6, "CONTRADICT": 5, "NEI": 5}
SCIFACT_DISTRACTORS = 60


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=Path("data/corpus"))
    parser.add_argument("--scifact", type=Path, help="directory with an extracted SciFact data/")
    args = parser.parse_args()
    sources = args.corpus / "sources"
    sources.mkdir(parents=True, exist_ok=True)

    records = {}
    for title, revid in FEVER_PAGES:
        records |= wikipedia_record(title, revid, "FEVER dev-set claims refer to this article")
    for title, revid in WIKICONTRADICT_PAGES:
        records |= wikipedia_record(
            title, revid, "WikiContradict (Hou et al., 2024) reports a contradiction in it"
        )
    for title, revid in SIMPLE_PAGES:
        records |= wikipedia_record(
            title, revid, "it is a second, separately written source on a FEVER subject", "simple"
        )
    claims, corpus = load_scifact(args.scifact)
    for doc_id, reason in select_scifact(claims, corpus).items():
        records |= scifact_record(corpus[doc_id], reason)

    written = 0
    for doc_id, record in sorted(records.items()):
        path = sources / f"{doc_id}.json"
        if path.exists():
            old = json.loads(path.read_text(encoding="utf-8"))
            for key in ("retrieved_at", "expected_sha256"):
                if key in old:
                    record[key] = old[key]
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written += 1
    print(f"wrote {written} provenance records to {sources}")
    return 0


def select_scifact(claims: list[dict], corpus: dict[int, dict]) -> dict[int, str]:
    """Doc ids to include, each with the reason it was selected."""
    rng = random.Random(SEED)
    by_label: dict[str, list[dict]] = {label: [] for label in SCIFACT_SAMPLE}
    for claim in claims:
        labels = {a["label"] for anns in claim["evidence"].values() for a in anns}
        by_label["NEI" if not labels else labels.pop()].append(claim)
    selected: dict[int, str] = {}
    for label, n in SCIFACT_SAMPLE.items():
        for claim in rng.sample(by_label[label], n):
            for doc_id in claim["cited_doc_ids"]:
                selected.setdefault(doc_id, f"cited by SciFact dev claim {claim['id']}")
    rest = sorted(set(corpus) - set(selected))
    for doc_id in rng.sample(rest, SCIFACT_DISTRACTORS):
        selected[doc_id] = "random distractor"
    return selected


def wikipedia_record(title: str, revid: int, reason: str, lang: str = "en") -> dict[str, dict]:
    host = f"{lang}.wikipedia.org"
    revision = _api(host, action="query", prop="revisions", revids=revid, rvprop="timestamp")
    page = revision["query"]["pages"][0]
    assert page["title"] == title, (page["title"], title)
    date = page["revisions"][0]["timestamp"][:10]
    slug = "".join(c if c.isalnum() else "-" for c in title.lower()).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    uri = f"https://{host}/w/index.php?{urllib.parse.urlencode({'oldid': revid})}"
    edition = "English" if lang == "en" else "Simple English"
    return {
        f"{'wiki' if lang == 'en' else 'simplewiki'}-{slug}": {
            "title": title,
            "source_name": f"Wikipedia, The Free Encyclopedia ({edition})",
            "authors": [],
            "affiliations": [],
            "source_uri": uri,
            "source_type": "reference",
            "publication_status": (
                f"{edition} Wikipedia article, revision {revid} of {date}. Written and edited by "
                "volunteer contributors (see the revision history); not peer-reviewed, and "
                "later revisions may differ. Included because " + reason + "."
            ),
            "disclosures": "None stated in the article.",
            "published": date,
            "rights": (
                "CC BY-SA 4.0. Attribution: Wikipedia contributors. Text-only extraction of "
                "the article prose; redistributed under the same license."
            ),
        }
    }


def scifact_record(doc: dict, reason: str) -> dict[str, dict]:
    doc_id = doc["doc_id"]
    return {
        f"scifact-{doc_id}": {
            "title": doc["title"].strip(),
            "source_name": "SciFact corpus (Wadden et al., 2020); abstract from S2ORC",
            "authors": [],
            "affiliations": [],
            "source_uri": f"{SCIFACT_URL}#doc_id={doc_id}",
            "source_type": "academic",
            "publication_status": (
                f"Abstract of a research article (Semantic Scholar corpus ID {doc_id}), as "
                "distributed in the SciFact corpus. The dataset does not record authors, "
                "venue, date or peer-review status, and they were not looked up. "
                f"Selected as: {reason}."
            ),
            "disclosures": (
                "Not available: the abstract states none and the full article was not checked."
            ),
            "published": None,
            "rights": "ODC-By 1.0 (S2ORC abstracts, via SciFact). Redistributed with attribution.",
        }
    }


def load_scifact(directory: Path | None) -> tuple[list[dict], dict[int, dict]]:
    """SciFact dev claims and corpus, from a local directory or the release tarball."""
    if directory is not None:
        read = lambda name: (directory / name).read_text(encoding="utf-8")  # noqa: E731
    else:
        request = urllib.request.Request(SCIFACT_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=300) as response:
            archive = tarfile.open(fileobj=io.BytesIO(response.read()), mode="r:gz")
        read = lambda name: archive.extractfile(f"data/{name}").read().decode("utf-8")  # noqa: E731
    claims = [json.loads(line) for line in read("claims_dev.jsonl").splitlines() if line]
    corpus = {}
    for line in read("corpus.jsonl").splitlines():
        if line:
            doc = json.loads(line)
            corpus[doc["doc_id"]] = doc
    return claims, corpus


def _api(host: str, **params) -> dict:
    query = urllib.parse.urlencode({**params, "format": "json", "formatversion": 2})
    request = urllib.request.Request(
        f"https://{host}/w/api.php?{query}", headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


if __name__ == "__main__":
    raise SystemExit(main())
