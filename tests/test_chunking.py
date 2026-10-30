"""Specification tests for chunk_document (Milestone 1).

Most tests pass a document through ``assert_chunking_invariants``, which checks
every rule of the ADR-008 contract at once. The remaining tests pin down specific
behaviors: boundary preference, greedy packing, IDs, and parameter validation.
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from factories import make_doc
from verity.ingest import chunk_document
from verity.models import Document, Passage


def assert_chunking_invariants(
    doc: Document, passages: list[Passage], max_chars: int, overlap: int
) -> None:
    text = doc.text
    covered = bytearray(len(text))

    for p in passages:
        # Exact, addressable slice of the source: the basis of every citation.
        assert text[p.start : p.end] == p.text, f"offset mismatch in {p.id}"
        assert p.doc_id == doc.id
        assert len(p.text) <= max_chars, f"{p.id} exceeds max_chars"
        assert p.text == p.text.strip(), f"{p.id} has surrounding whitespace"
        covered[p.start : p.end] = b"\x01" * (p.end - p.start)

    # Nothing meaningful is silently dropped.
    for i, ch in enumerate(text):
        if not ch.isspace():
            assert covered[i], f"non-whitespace char {ch!r} at {i} is not in any passage"

    for prev, nxt in zip(passages, passages[1:], strict=False):
        assert nxt.start > prev.start, "starts must strictly increase"
        assert nxt.end > prev.end, "ends must strictly increase"
        assert prev.end - nxt.start <= overlap, "overlap exceeds the limit"

    ids = [p.id for p in passages]
    assert len(ids) == len(set(ids)), "passage IDs must be unique"


# --- Parameter validation ------------------------------------------------------------


@pytest.mark.parametrize(
    ("max_chars", "overlap"),
    [(0, 0), (-5, 0), (100, -1), (100, 100), (100, 150)],
)
def test_rejects_invalid_parameters(max_chars: int, overlap: int) -> None:
    # overlap >= max_chars would let the chunker stop making progress (infinite loop).
    with pytest.raises(ValueError):
        chunk_document(make_doc("Some text."), max_chars=max_chars, overlap=overlap)


# --- Trivial inputs ------------------------------------------------------------------


@pytest.mark.parametrize("text", [" ", "\n\n\t  ", "  "])
def test_whitespace_only_document_yields_no_passages(text: str) -> None:
    assert chunk_document(make_doc(text), max_chars=100, overlap=10) == []


def test_short_document_is_one_trimmed_passage() -> None:
    doc = make_doc("   Hello world.   ")
    [p] = chunk_document(doc, max_chars=100, overlap=10)
    assert (p.start, p.end, p.text) == (3, 15, "Hello world.")


def test_document_exactly_max_chars_is_one_passage() -> None:
    doc = make_doc("x" * 50)
    passages = chunk_document(doc, max_chars=50, overlap=0)
    assert [p.text for p in passages] == ["x" * 50]


# --- Boundary preference and packing ---------------------------------------------------


def test_prefers_paragraph_breaks() -> None:
    p1 = "The commission interviewed more than twelve hundred people."
    p2 = "Its final report was released to the public in July 2004."
    doc = make_doc(f"{p1}\n\n{p2}")
    max_chars = max(len(p1), len(p2)) + 5  # each fits alone; together they don't
    assert len(doc.text) > max_chars

    passages = chunk_document(doc, max_chars=max_chars, overlap=0)

    assert [p.text for p in passages] == [p1, p2]


def test_prefers_sentence_ends_and_packs_greedily() -> None:
    sentences = [f"Sentence number {i} is short." for i in range(12)]
    doc = make_doc(" ".join(sentences))
    max_chars = 80

    passages = chunk_document(doc, max_chars=max_chars, overlap=0)

    assert_chunking_invariants(doc, passages, max_chars, overlap=0)
    for p in passages:
        assert p.text.startswith("Sentence") and p.text.endswith("."), p.text
    # Greedy: no two neighbouring passages could have been merged into one.
    for prev, nxt in zip(passages, passages[1:], strict=False):
        assert nxt.end - prev.start > max_chars


def test_overlong_sentence_splits_at_whitespace_not_mid_word() -> None:
    doc = make_doc("evidence " * 300)  # one 'sentence', no punctuation
    passages = chunk_document(doc, max_chars=97, overlap=20)

    assert_chunking_invariants(doc, passages, 97, 20)
    for p in passages:
        assert set(p.text.split()) == {"evidence"}, f"word was cut: {p.text!r}"


def test_single_token_longer_than_max_chars_is_hard_split() -> None:
    doc = make_doc("a" * 2500)
    passages = chunk_document(doc, max_chars=300, overlap=50)

    assert_chunking_invariants(doc, passages, 300, 50)
    assert len(passages) >= 9  # ceil(2500 / 300)


def test_zero_overlap_means_no_shared_characters() -> None:
    doc = make_doc(" ".join(f"Claim {i} is documented in the record." for i in range(40)))
    passages = chunk_document(doc, max_chars=120, overlap=0)

    assert_chunking_invariants(doc, passages, 120, 0)
    for prev, nxt in zip(passages, passages[1:], strict=False):
        assert nxt.start >= prev.end


def test_short_heading_is_packed_with_following_text() -> None:
    # A paragraph break that would leave the passage under half full is skipped in
    # favour of a later sentence end, so the heading isn't left on its own.
    body = " ".join(f"Finding {i} is recorded here." for i in range(10))
    doc = make_doc(f"Chapter 1\n\n{body}")
    passages = chunk_document(doc, max_chars=120, overlap=0)

    assert_chunking_invariants(doc, passages, 120, 0)
    assert passages[0].text.startswith("Chapter 1\n\nFinding 0")
    assert passages[0].text.endswith(".")


def test_sentence_end_detected_inside_closing_quotes() -> None:
    doc = make_doc(" ".join(['She wrote, "The report is final."'] * 10))
    passages = chunk_document(doc, max_chars=80, overlap=0)

    assert_chunking_invariants(doc, passages, 80, 0)
    assert all(p.text.endswith('."') for p in passages), [p.text for p in passages]


def test_cjk_splits_at_sentence_punctuation_without_spaces() -> None:
    doc = make_doc("这是一个测试句子。" * 120)
    passages = chunk_document(doc, max_chars=50, overlap=0)

    assert_chunking_invariants(doc, passages, 50, 0)
    assert all(p.text.endswith("。") for p in passages)


def test_overlap_begins_at_a_sentence_start_when_possible() -> None:
    doc = make_doc(" ".join(f"Fact {i} is on record." for i in range(30)))
    passages = chunk_document(doc, max_chars=100, overlap=50)

    assert_chunking_invariants(doc, passages, 100, 50)
    assert len(passages) > 1
    assert all(p.text.startswith("Fact") for p in passages), [p.text for p in passages]


def test_long_whitespace_gap_drops_overlap_instead_of_stalling() -> None:
    # The overlap start for passage 2 would only see whitespace within its window,
    # so the chunker must skip ahead to the next content rather than loop forever.
    doc = make_doc("alpha beta" + " " * 200 + "gamma")
    passages = chunk_document(doc, max_chars=20, overlap=10)

    assert_chunking_invariants(doc, passages, 20, 10)
    assert [p.text for p in passages] == ["alpha beta", "gamma"]


# --- Unicode: offsets are code-point indices ---------------------------------------


UNICODE_SAMPLES = {
    "arabic": "هذا نص تجريبي. " * 60,
    "cjk_no_spaces": "这是一个测试句子。" * 120,
    "emoji": "Evidence 🔍 matters. " * 80,
    "combining_marks": "Café au lait. " * 80,
    "mixed_newlines": "Line one.\r\nLine two.\n\n\nLine three. " * 40,
}


@pytest.mark.parametrize("name", UNICODE_SAMPLES)
def test_unicode_documents_keep_exact_offsets(name: str) -> None:
    doc = make_doc(UNICODE_SAMPLES[name])
    passages = chunk_document(doc, max_chars=150, overlap=30)
    assert passages
    assert_chunking_invariants(doc, passages, 150, 30)


# --- IDs and determinism -----------------------------------------------------------


LONG_TEXT = "\n\n".join(
    " ".join(f"Paragraph {p}, sentence {s}, states a fact." for s in range(6)) for p in range(8)
)


def test_chunking_is_deterministic() -> None:
    doc = make_doc(LONG_TEXT)
    assert chunk_document(doc, 200, 40) == chunk_document(doc, 200, 40)


def test_ids_are_stable_across_equal_documents() -> None:
    a = chunk_document(make_doc(LONG_TEXT), 200, 40)
    b = chunk_document(make_doc(LONG_TEXT), 200, 40)
    assert [p.id for p in a] == [p.id for p in b]


def test_ids_differ_between_documents() -> None:
    a = chunk_document(make_doc(LONG_TEXT, doc_id="doc-a"), 200, 40)
    b = chunk_document(make_doc(LONG_TEXT, doc_id="doc-b"), 200, 40)
    assert not {p.id for p in a} & {p.id for p in b}


def test_id_format_encodes_document_version_and_span() -> None:
    doc = make_doc("Hello world.", doc_id="doc")
    [p] = chunk_document(doc, max_chars=100, overlap=0)
    assert p.id == f"doc@{doc.sha256[:12]}:0-12"


def test_ids_differ_when_content_changes_under_same_doc_id() -> None:
    # A revised snapshot must not reuse old passage IDs; otherwise a stored
    # citation could silently resolve to text it never quoted.
    v1 = chunk_document(make_doc("Version one of the text.", doc_id="doc"), 100, 0)
    v2 = chunk_document(make_doc("Version two of the text.", doc_id="doc"), 100, 0)
    assert v1[0].id != v2[0].id


# --- Property-based: random documents, random parameters ---------------------------

ALPHABET = list("abcxyz ABC .!?,\n\t") + ["\n\n", "é", "ء", "中", "😀", "́", " "]


@settings(max_examples=300, deadline=None)
@given(
    text=st.lists(st.sampled_from(ALPHABET), min_size=1, max_size=400).map("".join),
    max_chars=st.integers(min_value=1, max_value=120),
    overlap_fraction=st.floats(min_value=0.0, max_value=0.9),
)
def test_invariants_hold_for_random_documents(
    text: str, max_chars: int, overlap_fraction: float
) -> None:
    overlap = min(int(max_chars * overlap_fraction), max_chars - 1)
    doc = make_doc(text)
    passages = chunk_document(doc, max_chars=max_chars, overlap=overlap)
    assert_chunking_invariants(doc, passages, max_chars, overlap)
