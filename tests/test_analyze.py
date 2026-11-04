"""Search-time text analysis: repairs, folding, stopwords and stemming."""

import pytest

from verity.retrieval.analyze import Analyzer, fold, s_stem

FULL = Analyzer()
RAW = Analyzer(repair_pdf_artifacts=False, remove_stopwords=False, stem=False)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("the South T ower at 9:59", ["south", "tower", "9", "59"]),  # kerning split
        ("New Y ork", ["new", "york"]),
        ("channels.T ypically the", ["channel", "typically"]),
        # line-break hyphenation
        ("re-\nduced the Fire Depart-\nment", ["reduced", "fire", "department"]),
        ("Baˇ zant and Zdenˇ ek; Ba ˇzant", ["bazant", "zdenek", "bazant"]),  # spacing caron
        ("ﬂoor trusses suﬃced", ["floor", "truss", "sufficed"]),  # ligatures (NFKC)
    ],
)
def test_repairs_pdf_extraction_artifacts(text: str, expected: list[str]) -> None:
    assert FULL(text) == expected


def test_kerning_repair_keeps_real_single_letter_labels() -> None:
    # Only overhanging capitals (T, V, W, Y) are kerned; other letters are labels.
    assert FULL("Stairwell\nB was also") == ["stairwell", "b", "also"]
    assert FULL("Case B temperatures and C columns") == ["case", "b", "temperature", "c", "column"]
    assert FULL("T his and W ere") == []  # joined words that are stopwords are removed


def test_line_break_hyphen_only_joins_lowercase_continuations() -> None:
    assert FULL("high-rise and WTC-\nBuilding") == ["high", "rise", "wtc", "building"]


def test_without_repair_artifacts_break_terms() -> None:
    assert RAW("South T ower") == ["south", "t", "ower"]
    assert RAW("re-\nduced") == ["re", "duced"]


def test_folding_removes_case_and_accents() -> None:
    assert fold("Bažant CAFÉ Zürich") == "bazant cafe zurich"


def test_letters_and_digits_are_separate_tokens() -> None:
    assert RAW("WTC7, WTC 7 and 5:20:52 p.m.") == [
        "wtc", "7", "wtc", "7", "and", "5", "20", "52", "p", "m",
    ]  # fmt: skip


def test_stopwords_are_removed_including_negations() -> None:
    assert FULL("It was not struck by an airplane") == ["struck", "airplane"]
    assert Analyzer(remove_stopwords=False)("not struck") == ["not", "struck"]


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("towers", "tower"),
        ("fires", "fire"),
        ("stories", "story"),
        ("trusses", "truss"),
        ("matches", "match"),
        ("boxes", "box"),
        ("status", "status"),  # -us kept
        ("glass", "glass"),  # -ss kept
        ("shoes", "shoe"),
        ("gas", "gas"),  # too short
        ("1990s", "1990s"),  # not purely alphabetic
        ("fired", "fired"),  # only plurals are touched
    ],
)
def test_s_stemmer(token: str, expected: str) -> None:
    assert s_stem(token) == expected


def test_query_and_passage_variants_meet() -> None:
    passage = FULL("the ﬂoor trusses of the North T ower")
    query = FULL("Floor truss, north tower")
    assert set(query) <= set(passage)
