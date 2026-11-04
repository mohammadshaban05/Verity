"""Search-time text analysis: repairs, folding, stopwords and stemming."""

import pytest

from verity.retrieval.analyze import Analyzer, fold, s_stem

FULL = Analyzer()
REPAIR = Analyzer(repair_pdf_artifacts=True)
RAW = Analyzer(repair_pdf_artifacts=False, remove_stopwords=False, stem=False)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("the T able at 9:59", ["table", "9", "59"]),  # kerning split
        ("New Y ork", ["new", "york"]),
        ("channels.T ypically the", ["channel", "typically"]),
        # line-break hyphenation
        ("re-\nduced the Health Depart-\nment", ["reduced", "health", "department"]),
        ("Dvoˇ rák and Zdenˇ ek; Dvo ˇrák", ["dvorak", "zdenek", "dvorak"]),  # spacing caron
        ("ﬂoor glasses suﬃced", ["floor", "glass", "sufficed"]),  # ligatures (NFKC)
    ],
)
def test_repairs_pdf_extraction_artifacts(text: str, expected: list[str]) -> None:
    assert REPAIR(text) == expected


def test_kerning_repair_keeps_other_single_letter_labels() -> None:
    # Only overhanging capitals (T, V, W, Y) are kerned; other letters are labels.
    assert REPAIR("Group\nB was also") == ["group", "b", "also"]
    assert REPAIR("Case B samples and C groups") == ["case", "b", "sample", "c", "group"]
    assert REPAIR("T his and W ere") == []  # joined words that are stopwords are removed


def test_kerning_repair_falsely_joins_real_one_letter_words() -> None:
    # Why repair is off by default: in non-PDF text these are real words.
    assert REPAIR("T cells and the V rocket") == ["tcell", "vrocket"]  # joined, then stemmed
    assert FULL("T cells and the V rocket") == ["t", "cell", "v", "rocket"]


def test_repair_is_off_by_default() -> None:
    assert not Analyzer().repair_pdf_artifacts
    assert FULL("re-\nduced") == ["re", "duced"]


def test_line_break_hyphen_only_joins_lowercase_continuations() -> None:
    assert REPAIR("long-term and COVID-\nRelated") == ["long", "term", "covid", "related"]


def test_without_repair_artifacts_break_terms() -> None:
    assert RAW("T able") == ["t", "able"]
    assert RAW("re-\nduced") == ["re", "duced"]


def test_folding_removes_case_and_accents() -> None:
    assert fold("Dvořák CAFÉ Zürich") == "dvorak cafe zurich"


def test_letters_and_digits_are_separate_tokens() -> None:
    assert RAW("COVID19, COVID 19 and 5:20:52 p.m.") == [
        "covid", "19", "covid", "19", "and", "5", "20", "52", "p", "m",
    ]  # fmt: skip


def test_stopwords_are_removed_including_negations() -> None:
    assert FULL("It was not caused by a virus") == ["caused", "virus"]
    assert Analyzer(remove_stopwords=False)("not caused") == ["not", "caused"]


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("rivers", "river"),
        ("cells", "cell"),
        ("stories", "story"),
        ("glasses", "glass"),
        ("matches", "match"),
        ("boxes", "box"),
        ("status", "status"),  # -us kept
        ("glass", "glass"),  # -ss kept
        ("shoes", "shoe"),
        ("gas", "gas"),  # too short
        ("1990s", "1990s"),  # not purely alphabetic
        ("studied", "studied"),  # only plurals are touched
    ],
)
def test_s_stemmer(token: str, expected: str) -> None:
    assert s_stem(token) == expected


def test_query_and_passage_variants_meet() -> None:
    passage = REPAIR("the ﬂoor glasses of the North T able")
    query = REPAIR("Floor glass, north table")
    assert set(query) <= set(passage)
