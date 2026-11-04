"""BM25 scoring: exact formula, reference parity, and retrieval edge cases."""

import math
from collections import Counter

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from rank_bm25 import BM25Okapi

from factories import make_doc
from verity.ingest import chunk_document
from verity.models import Passage
from verity.retrieval import Analyzer, BM25Retriever

RAW = Analyzer(repair_pdf_artifacts=False, remove_stopwords=False, stem=False)


def passages(*texts: str) -> list[Passage]:
    return [
        Passage(id=f"p{i}", doc_id="doc", start=0, end=len(t), text=t) for i, t in enumerate(texts)
    ]


def brute_force_scores(texts: list[str], query: str, k1: float, b: float) -> list[float]:
    """The BM25 formula written out directly, as an independent reference."""
    docs = [RAW(t) for t in texts]
    n, avgdl = len(docs), sum(map(len, docs)) / len(docs)
    scores = []
    for doc in docs:
        tf = Counter(doc)
        total = 0.0
        for term in RAW(query):
            df = sum(term in d for d in docs)
            if df == 0 or tf[term] == 0:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            total += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * len(doc) / avgdl))
        scores.append(total)
    return scores


# --- Exact scoring -------------------------------------------------------------------


def test_matches_hand_computed_score() -> None:
    # N=2, df(rain)=1 -> idf = ln(1 + 1.5/1.5) = ln 2; both passages have length 2 = avgdl.
    index = BM25Retriever(passages("rain fell", "wind cloud"), analyzer=RAW, k1=1.2, b=0.75)
    [hit] = index.search("rain")
    assert hit.passage.id == "p0"
    assert hit.score == pytest.approx(math.log(2) * 1 * 2.2 / (1 + 1.2))


words = st.sampled_from(["rain", "wind", "river", "ocean", "snow", "storm", "glacier", "x"])


@settings(max_examples=200, deadline=None)
@given(
    texts=st.lists(st.lists(words, min_size=1, max_size=12).map(" ".join), min_size=1, max_size=8),
    query=st.lists(words, min_size=1, max_size=4).map(" ".join),
    k1=st.floats(0.0, 3.0),
    b=st.floats(0.0, 1.0),
)
def test_matches_brute_force_formula(texts: list[str], query: str, k1: float, b: float) -> None:
    index = BM25Retriever(passages(*texts), analyzer=RAW, k1=k1, b=b)
    assert index.scores(query) == pytest.approx(brute_force_scores(texts, query, k1, b))


@settings(max_examples=200, deadline=None)
@given(
    texts=st.lists(st.lists(words, min_size=1, max_size=12).map(" ".join), min_size=1, max_size=8),
    query=st.lists(words, min_size=1, max_size=4).map(" ".join),
)
def test_okapi_variant_matches_rank_bm25_exactly(texts: list[str], query: str) -> None:
    reference = BM25Okapi([RAW(t) for t in texts], k1=1.5, b=0.75, epsilon=0.25)
    ours = BM25Retriever(passages(*texts), analyzer=RAW, k1=1.5, b=0.75, idf="okapi")
    assert ours.scores(query) == pytest.approx(list(reference.get_scores(RAW(query))), abs=1e-9)


def test_explain_sums_to_score() -> None:
    index = BM25Retriever(passages("rain wind rain", "wind cloud", "river"))
    [top, *_] = index.search("rain wind river")
    assert sum(index.explain("rain wind river", top.passage.id).values()) == pytest.approx(
        top.score
    )


# --- Missing terms and irrelevant passages -------------------------------------------


@pytest.mark.parametrize("query", ["volcano", "", "   ", "the of and"])
def test_queries_without_known_terms_return_nothing(query: str) -> None:
    index = BM25Retriever(passages("rain fell through valleys", "wind clouds shifted"))
    assert index.search(query) == []


def test_unknown_query_terms_are_ignored() -> None:
    index = BM25Retriever(passages("rain fell", "wind cloud", "river flood"))
    assert index.scores("rain volcano") == index.scores("rain")


def test_irrelevant_passages_are_never_returned_even_below_k() -> None:
    index = BM25Retriever(passages("rain fell", "wind cloud", "river flood"))
    hits = index.search("rain", k=10)
    assert [h.passage.id for h in hits] == ["p0"]


# --- Duplicate content ------------------------------------------------------------------


def test_duplicate_passages_tie_and_keep_a_stable_order() -> None:
    index = BM25Retriever(passages("rain on valley twelve", "wind", "rain on valley twelve"))
    first, second = index.search("rain twelve")
    assert first.score == second.score
    assert [first.passage.id, second.passage.id] == ["p0", "p2"]


def test_duplicates_lower_the_idf_of_their_terms() -> None:
    single = BM25Retriever(passages("glacier melt", "wind", "cloud", "river"))
    duplicated = BM25Retriever(passages("glacier melt", "glacier melt", "cloud", "river"))
    assert duplicated.idf("glacier") < single.idf("glacier")


# --- Length normalization and saturation -------------------------------------------


def test_longer_passage_scores_lower_for_the_same_term_frequency() -> None:
    short, long = "river seventy nine", "river " + " ".join(["filler"] * 60)
    index = BM25Retriever(passages(short, long, "unrelated text"), analyzer=RAW, b=0.75)
    scores = index.scores("river")
    assert scores[0] > scores[1] > 0


def test_b_zero_disables_length_normalization() -> None:
    short, long = "river seventy nine", "river " + " ".join(["filler"] * 60)
    index = BM25Retriever(passages(short, long, "unrelated text"), analyzer=RAW, b=0.0)
    scores = index.scores("river")
    assert scores[0] == pytest.approx(scores[1])


def test_term_repetition_saturates() -> None:
    texts = ["rain " * n + "end" for n in (1, 5, 50)] + ["wind"] * 3
    index = BM25Retriever(passages(*texts), analyzer=RAW, k1=1.2, b=0.0)
    s1, s5, s50, *_ = index.scores("rain")
    assert s1 < s5 < s50 < index.idf("rain") * (1.2 + 1)
    assert s50 - s5 < s5 - s1  # diminishing returns


def test_rare_terms_outweigh_common_terms() -> None:
    texts = ["rain wind", "rain cloud", "rain river", "rain glacier melt"]
    index = BM25Retriever(passages(*texts), analyzer=RAW)
    assert index.idf("melt") > index.idf("rain")
    assert index.search("rain melt")[0].passage.id == "p3"


def test_long_document_does_not_drown_short_one() -> None:
    # A 300-passage document and a 2-passage document share the corpus. The short
    # document's precise match still ranks first.
    long_doc = make_doc("Wind clouds and harbor rains. " * 2000, doc_id="long")
    short_doc = make_doc("River 79 flooded after the glacier melted off its ridge.", doc_id="short")
    pool = chunk_document(long_doc, 200, 40) + chunk_document(short_doc, 200, 40)
    hits = BM25Retriever(pool).search("glacier melted off ridge river 79", k=3)
    assert hits[0].passage.doc_id == "short"


# --- Determinism, validation, snapshot integrity --------------------------------------


def test_hits_return_original_passages_unchanged() -> None:
    # Analysis (here with PDF repair) changes index terms, never the passage text.
    original = passages("the North T able opened at 9:59")
    [hit] = BM25Retriever(original, analyzer=Analyzer(repair_pdf_artifacts=True)).search("table")
    assert hit.passage is original[0]
    assert hit.passage.text == "the North T able opened at 9:59"


def test_ranking_is_deterministic() -> None:
    texts = [f"rain valley {i % 3} river" for i in range(30)]
    a = BM25Retriever(passages(*texts)).search("rain river valley", k=30)
    b = BM25Retriever(passages(*texts)).search("rain river valley", k=30)
    assert a == b
    assert [h.rank for h in a] == list(range(1, 31))


@pytest.mark.parametrize("kwargs", [{"k1": -0.1}, {"b": 1.5}, {"b": -0.1}, {"idf": "tfidf"}])
def test_rejects_invalid_parameters(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        BM25Retriever(passages("rain"), **kwargs)


def test_rejects_invalid_k() -> None:
    with pytest.raises(ValueError):
        BM25Retriever(passages("rain")).search("rain", k=0)


def test_empty_index() -> None:
    index = BM25Retriever([])
    assert index.search("rain") == [] and index.scores("rain") == []
