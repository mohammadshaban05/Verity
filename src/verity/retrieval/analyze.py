"""Search-time text analysis: turn passage or query text into index terms (ADR-011).

This runs only when building the index and parsing queries. Stored snapshots are
never modified, and passages are still identified and cited by their exact
offsets into the original text.

Pipeline:
  1. (repair) drop spacing diacritics that PDF extraction splits off letters:
     "Dvoˇ rák" -> "Dvorák". This runs before NFKC, which would otherwise turn
     them into a space plus a combining mark.
  2. NFKC: ligatures and compatibility forms ("ﬂoor" -> "floor", "ﬁ" -> "fi").
  3. (repair) join words hyphenated across a line break ("re-\\nduced" ->
     "reduced"), and kerning splits where an overhanging capital (T, V, W, Y) is
     detached from its word ("T able" -> "Table").
  4. Case-fold and strip accents.
  5. Split into runs of letters and runs of digits ("COVID19" -> "covid", "19").
  6. (optional) remove English stopwords.
  7. (optional) light plural stemming (Harman's S-stemmer plus a sibilant rule).

The repair steps are off by default. They target text extracted from PDFs, and
the kerning rule cannot tell an artifact from a real one-letter word: in the
seed corpus, which contains no PDFs, all of its matches are false joins
("T cells" -> "tcells", "V rocket" -> "vrocket"). Turn repair on only for
PDF-derived text, and check its matches first.
"""

import re
import unicodedata
from dataclasses import dataclass

# A standard English stopword list. It includes negations ("no", "not", "nor"):
# BM25 can't use negation anyway (ADR-011).
STOPWORDS = frozenset(
    """a about above after again against all am an and any are as at be because been before
    being below between both but by can could did do does doing down during each few for from
    further had has have having he her here hers herself him himself his how i if in into is
    it its itself just me more most my myself no nor not of off on once only or other our ours
    ourselves out over own same she should so some such than that the their theirs them
    themselves then there these they this those through to too under until up very was we
    were what when where which while who whom why will with would you your yours yourself
    yourselves""".split()
)

_SPACING_DIACRITIC = re.compile(r"(?<=[^\W\d_]) ?[ˇ´`¨˜ˆ¸˘˚] ?(?=[^\W\d_])")
_LINE_BREAK_HYPHEN = re.compile(r"(?<=[^\W\d_])-[ \t]*\n[ \t]*(?=[a-z])")
# Typographic kerning tucks the next letter under an overhanging capital; some PDF
# extractors then emit a space there. Only these capitals were affected in the PDFs
# examined in M2.
_KERNING_SPLIT = re.compile(r"\b([TVWY]) ([a-z]{2,})\b")
_TOKEN = re.compile(r"[^\W\d_]+|\d+")


@dataclass(frozen=True)
class Analyzer:
    """Configurable text-to-terms function. Defaults are the retrieval baseline."""

    repair_pdf_artifacts: bool = False
    remove_stopwords: bool = True
    stem: bool = True

    def __call__(self, text: str) -> list[str]:
        if self.repair_pdf_artifacts:
            text = _SPACING_DIACRITIC.sub("", text)
        text = unicodedata.normalize("NFKC", text)
        if self.repair_pdf_artifacts:
            text = _LINE_BREAK_HYPHEN.sub("", text)
            text = _KERNING_SPLIT.sub(r"\1\2", text)
        tokens = _TOKEN.findall(fold(text))
        if self.remove_stopwords:
            tokens = [t for t in tokens if t not in STOPWORDS]
        if self.stem:
            tokens = [s_stem(t) for t in tokens]
        return tokens


def fold(text: str) -> str:
    """Case-fold and remove accents: "Dvořák" -> "dvorak"."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def s_stem(token: str) -> str:
    """Harman's S-stemmer (1991): conflates regular English plurals only.

    Deliberately weak. It never merges different words ("fire" vs "fired"),
    at the cost of missing some variants that Porter stemming would catch.
    """
    if len(token) <= 3 or not token.isalpha():
        return token
    # Sibilant plurals ("glasses", "matches", "boxes") drop "es". Harman's rules
    # alone would give "glasse", which never matches "glass".
    if token.endswith(("sses", "ches", "shes", "xes")):
        return token[:-2]
    if token.endswith("ies") and not token.endswith(("eies", "aies")):
        return token[:-3] + "y"
    if token.endswith("es") and not token.endswith(("aes", "ees", "oes")):
        return token[:-1]
    if token.endswith("s") and not token.endswith(("us", "ss")):
        return token[:-1]
    return token
