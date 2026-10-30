"""Turn Documents into Passages with exact character offsets.

Algorithm (ADR-008): a sliding window that snaps backward to the best boundary.

1. Scan the text once and record every boundary where a passage may end:
   paragraph breaks, sentence ends and word gaps. Also record where the next
   sentence or word begins.
2. From the current start, look at the window ``[start, start + max_chars]``.
   Cut at the latest paragraph break in the window. If that would make the
   passage less than half full, use the latest sentence end instead, then the
   latest word gap. Only cut mid-word when the window has no boundary at all.
3. Start the next passage up to ``overlap`` characters before the previous
   end, at a sentence start if possible, otherwise at a word start, and never
   mid-word. If no such start exists, don't overlap.

Every passage is a slice ``doc.text[start:end]`` described by its offsets. Text is
never rebuilt by joining pieces, so the offsets can't drift away from the source.
"""

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from verity.models import Document, Passage

_WHITESPACE_RUN = re.compile(r"\s+")
_NON_WHITESPACE = re.compile(r"\S")
# CJK sentence punctuation is usually followed directly by the next sentence, with no space.
_SPACELESS_SENTENCE_END = re.compile(r"[。！？](?=\S)")
_SENTENCE_TERMINATORS = frozenset(".!?…。！？")
_CLOSING_PUNCTUATION = frozenset("\"')]}»”’")
_LINE_BREAKS = ("\n", "\u2028")

# A higher-ranked boundary is used only if the passage would be at least this full.
MIN_FILL_RATIO = 0.5


@dataclass(frozen=True)
class _Boundaries:
    """Sorted candidate positions in one document's text.

    ``cuts`` lists positions where a passage may end, grouped by strength:
    (paragraph, sentence, word). Each position appears only in its strongest group.
    """

    cuts: tuple[list[int], list[int], list[int]]
    sentence_starts: list[int]
    word_starts: list[int]


def chunk_document(doc: Document, max_chars: int = 1000, overlap: int = 200) -> list[Passage]:
    """Split ``doc.text`` into passages that each fit within ``max_chars``.

    Contract (ADR-008):
      - Raises ValueError unless ``max_chars >= 1`` and ``0 <= overlap < max_chars``.
      - Returns [] for whitespace-only text.
      - Every passage satisfies ``doc.text[p.start:p.end] == p.text`` and
        ``p.doc_id == doc.id``.
      - ``len(p.text) <= max_chars``: a hard cap, including for oversized sentences.
      - Passages have no leading/trailing whitespace (``p.text == p.text.strip()``).
      - Every non-whitespace character of ``doc.text`` is inside some passage.
      - Passages are ordered: ``start`` and ``end`` both strictly increase.
      - Consecutive passages share at most ``overlap`` characters.
      - Split points are chosen in order of preference: paragraph break,
        sentence end, whitespace, and only then mid-word. Passages are packed
        greedily up to ``max_chars``.
      - Passage IDs are ``"<doc_id>@<first 12 hex of sha256>:<start>-<end>"``:
        deterministic, unique within the document, and different for each
        content version.

    Defaults: about 1000 chars is roughly 200-250 tokens of English, which
    fits small embedding models (e.g. 256-token limits) with some room to spare.
    """
    if max_chars < 1:
        raise ValueError(f"max_chars must be >= 1, got {max_chars}")
    if not 0 <= overlap < max_chars:
        # overlap >= max_chars would let a window fail to move forward (infinite loop).
        raise ValueError(f"overlap must satisfy 0 <= overlap < max_chars, got {overlap}")

    text = doc.text
    bounds = _find_boundaries(text)
    passages: list[Passage] = []

    start = _next_content(text, 0)
    prev_end = 0
    while start < len(text):
        # A passage must end after the previous one, so its end search begins at prev_end.
        end = _choose_end(text, bounds, start, floor=max(start, prev_end), max_chars=max_chars)
        if end is None:
            # The overlap region was followed by nothing but whitespace within the
            # window. Give up the overlap and start at the next real content.
            start = _next_content(text, prev_end)
            continue

        passages.append(
            Passage(
                id=passage_id(doc, start, end),
                doc_id=doc.id,
                start=start,
                end=end,
                text=text[start:end],
            )
        )
        prev_end = end

        next_content = _next_content(text, end)
        if next_content >= len(text):
            break
        start = _choose_next_start(bounds, start, end, overlap, next_content)

    return passages


def passage_id(doc: Document, start: int, end: int) -> str:
    """The canonical ID of the span ``doc.text[start:end]``."""
    # The hash prefix ties the ID to one exact version of the text. A revised
    # document gets new passage IDs even when the offsets are the same.
    return f"{doc.id}@{doc.sha256[:12]}:{start}-{end}"


def _find_boundaries(text: str) -> _Boundaries:
    cuts: tuple[list[int], list[int], list[int]] = ([], [], [])
    paragraph, sentence, word = cuts
    sentence_starts: list[int] = []
    word_starts: list[int] = []

    for run in _WHITESPACE_RUN.finditer(text):
        cut, next_start = run.start(), run.end()
        if cut == 0:
            continue  # leading whitespace: nothing before it to end a passage
        run_text = run.group()
        if sum(run_text.count(b) for b in _LINE_BREAKS) >= 2 or "\u2029" in run_text:
            paragraph.append(cut)
            is_sentence_boundary = True
        elif _ends_sentence(text, cut):
            sentence.append(cut)
            is_sentence_boundary = True
        else:
            word.append(cut)
            is_sentence_boundary = False
        if next_start < len(text):
            word_starts.append(next_start)
            if is_sentence_boundary:
                sentence_starts.append(next_start)

    for match in _SPACELESS_SENTENCE_END.finditer(text):
        sentence.append(match.end())
        sentence_starts.append(match.end())
        word_starts.append(match.end())

    for positions in (*cuts, sentence_starts, word_starts):
        positions.sort()
    return _Boundaries(cuts=cuts, sentence_starts=sentence_starts, word_starts=word_starts)


def _ends_sentence(text: str, end: int) -> bool:
    """True if ``text[:end]`` ends with a sentence terminator, ignoring closing quotes."""
    i = end - 1
    while i >= 0 and text[i] in _CLOSING_PUNCTUATION:
        i -= 1
    return i >= 0 and text[i] in _SENTENCE_TERMINATORS


def _choose_end(
    text: str, bounds: _Boundaries, start: int, floor: int, max_chars: int
) -> int | None:
    """Pick the end of the passage starting at ``start``. Returns None if the only
    text in ``(floor, start + max_chars]`` is whitespace."""
    limit = start + max_chars
    if limit >= len(text):
        cut = len(text)  # the rest of the document fits
    else:
        cut = _best_cut(bounds, start, floor, limit, min_fill=int(max_chars * MIN_FILL_RATIO))
    end = start + len(text[start:cut].rstrip())
    return end if end > floor else None


def _best_cut(bounds: _Boundaries, start: int, floor: int, limit: int, min_fill: int) -> int:
    latest = [_latest(positions, floor, limit) for positions in bounds.cuts]
    # Use the strongest boundary that still fills at least half the window, so a
    # short heading isn't left as a passage of its own.
    for cut in latest:
        if cut is not None and cut - start >= min_fill:
            return cut
    # Otherwise a short passage at a real boundary beats cutting a word in half.
    return max((c for c in latest if c is not None), default=limit)


def _choose_next_start(
    bounds: _Boundaries, start: int, end: int, overlap: int, next_content: int
) -> int:
    if overlap == 0:
        return next_content
    # Start no more than `overlap` chars back, and strictly after the previous start.
    lo = max(end - overlap, start + 1)
    for positions in (bounds.sentence_starts, bounds.word_starts):
        candidate = _earliest(positions, lo, end)
        if candidate is not None:
            return candidate
    return next_content


def _next_content(text: str, pos: int) -> int:
    """Index of the first non-whitespace character at or after ``pos``, else len(text)."""
    match = _NON_WHITESPACE.search(text, pos)
    return match.start() if match else len(text)


def _latest(positions: list[int], lo: int, hi: int) -> int | None:
    """Largest position p with lo < p <= hi."""
    i = bisect_right(positions, hi) - 1
    return positions[i] if i >= 0 and positions[i] > lo else None


def _earliest(positions: list[int], lo: int, hi: int) -> int | None:
    """Smallest position p with lo <= p < hi."""
    i = bisect_left(positions, lo)
    return positions[i] if i < len(positions) and positions[i] < hi else None
