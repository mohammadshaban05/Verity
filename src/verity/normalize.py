"""Text normalization applied once, at ingestion, before a Document is hashed.

Normalize only encoding noise and never content. The stored snapshot should
match what the source says, character for character, apart from differences
that are invisible to a reader. Everything later in the pipeline (offsets,
passages, citations) refers to the normalized text, so these rules are
versioned: changing them changes hashes, and must bump the version.

Rules for ``NORMALIZATION_VERSION`` "utf8-nfc-lf-v1":
  1. Bytes must be valid UTF-8. A leading byte-order mark is removed.
  2. NUL characters are rejected (they indicate a binary or corrupted file).
  3. Line endings become "\\n" ("\\r\\n", a lone "\\r", and U+0085 NEL).
  4. Control characters are removed, except tab, newline and form feed.
     Form feed is kept because PDF extraction uses it to mark page breaks,
     which allows page numbers to be recovered later.
  5. Unicode NFC composition, so "e" + U+0301 and "é" become the same text.

Deliberately not done:
  - NFKC: it changes content ("x²" -> "x2", "ﬁ" -> "fi").
  - Curly-to-straight quotes, whitespace collapsing, dehyphenation: these
    change what the source literally says. Comparisons that should ignore
    these differences (e.g. citation matching in M3) normalize at comparison
    time, and leave the stored text unchanged.
"""

import re
import unicodedata

NORMALIZATION_VERSION = "utf8-nfc-lf-v1"

_LINE_ENDINGS = re.compile(r"\r\n?|\x85")
# C0 and C1 control characters except \t (09), \n (0A) and \f (0C).
_DISALLOWED_CONTROLS = re.compile(r"[\x01-\x08\x0b\x0e-\x1f\x7f-\x9f]")


class NormalizationError(ValueError):
    """Raw bytes can't be turned into a valid snapshot text."""


def decode_utf8(data: bytes) -> str:
    """Decode strict UTF-8, dropping a leading byte-order mark."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise NormalizationError(
            f"not valid UTF-8 at byte {exc.start} ({data[exc.start : exc.start + 4]!r}); "
            "convert the file to UTF-8"
        ) from exc


def normalize_text(text: str) -> str:
    """Apply the normalization rules to already-decoded text. Idempotent."""
    if "\x00" in text:
        raise NormalizationError(
            f"contains a NUL character at index {text.index(chr(0))}; "
            "likely a binary or corrupted file"
        )
    text = _LINE_ENDINGS.sub("\n", text)
    text = _DISALLOWED_CONTROLS.sub("", text)
    return unicodedata.normalize("NFC", text)


def normalize_bytes(data: bytes) -> str:
    """Decode and normalize a raw file's contents."""
    return normalize_text(decode_utf8(data))
