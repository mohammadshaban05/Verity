"""Text normalization: encoding noise is removed, content is never changed."""

import unicodedata

import pytest
from hypothesis import given
from hypothesis import strategies as st

from verity.normalize import NormalizationError, decode_utf8, normalize_bytes, normalize_text


def test_line_endings_become_lf() -> None:
    assert normalize_text("a\r\nb\rc\x85d\ne") == "a\nb\nc\nd\ne"


def test_composes_to_nfc() -> None:
    decomposed = unicodedata.normalize("NFD", "café Zürich")
    assert normalize_text(decomposed) == unicodedata.normalize("NFC", "café Zürich")


def test_removes_control_characters_but_keeps_tab_newline_and_page_breaks() -> None:
    assert normalize_text("a\x01b\x0bc\x1bd\x7fe\x9ff\tg\nh\fi") == "abcdef\tg\nh\fi"


@pytest.mark.parametrize(
    "text",
    [
        "x² and H₂O",  # NFKC would turn these into "x2" / "H2O"
        "ﬁnal ﬂoor",  # ligatures stay as extracted
        "“curly” ‘quotes’ — dashes",
        "  double  spaces  and trailing  ",
        "hy-\nphenated",
        " non-breaking separator",
    ],
)
def test_content_is_not_altered(text: str) -> None:
    assert normalize_text(text) == text


def test_rejects_nul() -> None:
    with pytest.raises(NormalizationError, match="NUL"):
        normalize_text("abc\x00def")


def test_decode_strips_utf8_bom() -> None:
    assert decode_utf8(b"\xef\xbb\xbfHello") == "Hello"


@pytest.mark.parametrize(
    "data",
    [
        "caf\xe9".encode("latin-1"),  # Latin-1 'é' is invalid UTF-8
        b"\xff\xfeH\x00i\x00",  # UTF-16 with BOM
        b"truncated \xe2\x80",  # incomplete multi-byte sequence
    ],
)
def test_rejects_invalid_utf8_with_byte_position(data: bytes) -> None:
    with pytest.raises(NormalizationError, match="not valid UTF-8 at byte"):
        decode_utf8(data)


def test_normalize_bytes_combines_decoding_and_normalization() -> None:
    assert normalize_bytes(b"\xef\xbb\xbfLine\r\nCafe\xcc\x81") == "Line\nCafé"


@given(st.text())
def test_normalization_is_idempotent(text: str) -> None:
    if "\x00" in text:
        return
    once = normalize_text(text)
    assert normalize_text(once) == once
