"""HTML→plain extraction + Snowball stemming.

Both helpers run identically on index and query (query happens client-side
in the Worker using snowballstem JS). Keep the algorithms in lockstep.
"""

from __future__ import annotations

import re
import warnings

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning
import snowballstemmer

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

_WORD_RE = re.compile(r"\w+", re.UNICODE)
_HAS_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_WS_RE = re.compile(r"\s+")

_stemmer = None


def stemmer():
    global _stemmer
    if _stemmer is None:
        _stemmer = snowballstemmer.stemmer("russian")
    return _stemmer


def to_plain(message_parsed: str) -> str:
    """Return plain text suitable for snippet rendering."""
    if not message_parsed:
        return ""
    soup = BeautifulSoup(message_parsed, "lxml")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for blockquote in soup.find_all("blockquote"):
        # Keep quote text but strip the "X said:" header XF injects.
        head = blockquote.find(attrs={"class": "bbCodeBlock-title"})
        if head:
            head.decompose()
    text = soup.get_text(separator=" ")
    return _WS_RE.sub(" ", text).strip()


def stem_text(text: str) -> str:
    """Lowercase, normalise ё→е, Snowball-stem Cyrillic; keep ASCII as-is.

    The JS Snowball port we use in the Worker (`snowball-stemmers`) keeps
    `ё` distinct from `е`, while the Python `snowballstemmer` normalises
    internally — so without the explicit replace here the index and the
    Worker would disagree on every word containing `ё`.
    """
    if not text:
        return ""
    tokens = _WORD_RE.findall(text)
    s = stemmer()
    out = []
    for tok in tokens:
        low = tok.lower().replace("ё", "е")
        if _HAS_CYRILLIC.search(low):
            out.append(s.stemWord(low))
        else:
            out.append(low)
    return " ".join(out)
