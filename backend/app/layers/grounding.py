"""Locate model-supplied quotes inside the article text (Layer 2).

Grounding answers one question: does this passage exist in raw_text? It says
nothing about whether the claim built from it is true. No web search, no
corroboration, no truth judgement happens here.

Matching is exact first, then a single retry on normalised forms of both
strings. There is deliberately no fuzzy or approximate matching: a near-miss
is reported as not_found so the journalist sees it.
"""

from __future__ import annotations

import unicodedata

from app.schemas.envelope import ClaimSource, Grounding, TextSegment

_QUOTE_DASH_MAP = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201b": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u00ab": '"',
    "\u00bb": '"',
    "\u2032": "'",
    "\u2033": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
}


def normalise_with_map(text: str) -> tuple[str, list[int]]:
    """Normalise `text` and record, per output character, its source index.

    NFKC is applied per character so that expansions (ligatures, fullwidth
    forms) never desynchronise the offset map. Whitespace runs collapse to a
    single space mapped to the first character of the run.
    """
    out: list[str] = []
    index_map: list[int] = []
    prev_was_space = False
    for i, ch in enumerate(text or ""):
        if ch.isspace():
            if prev_was_space:
                continue
            out.append(" ")
            index_map.append(i)
            prev_was_space = True
            continue
        prev_was_space = False
        for norm_ch in unicodedata.normalize("NFKC", _QUOTE_DASH_MAP.get(ch, ch)):
            out.append(norm_ch)
            index_map.append(i)
    return "".join(out), index_map


def normalise(text: str) -> str:
    return normalise_with_map(text)[0]


def locate_quote(raw_text: str, quote: str | None) -> tuple[int | None, int | None, Grounding]:
    """Find `quote` in `raw_text`, returning raw offsets and how it matched.

    Returns (span_start, span_end, grounding) where
    raw_text[span_start:span_end] is the located passage.
    """
    needle = (quote or "").strip()
    if not needle or not raw_text:
        return None, None, "not_found"

    exact = raw_text.find(needle)
    if exact != -1:
        return exact, exact + len(needle), "exact"

    haystack, index_map = normalise_with_map(raw_text)
    normalised_needle = normalise(needle).strip()
    if not normalised_needle:
        return None, None, "not_found"
    found = haystack.find(normalised_needle)
    if found == -1:
        return None, None, "not_found"
    start = index_map[found]
    end = index_map[found + len(normalised_needle) - 1] + 1
    return start, end, "normalised"


def segment_source_for_span(
    segments: list[TextSegment],
    span_start: int | None,
    span_end: int | None,
) -> ClaimSource | None:
    """Which Layer 1 segment(s) a located span falls inside.

    Returns None when the claim is ungrounded or Layer 1 recorded no segments.
    TODO: Layer 1 only emits segments when it ran; envelopes restored from
    before segments existed will report None here rather than guessing.
    """
    if not segments or span_start is None or span_end is None:
        return None
    kinds = {
        seg.source
        for seg in segments
        if seg.start < span_end and span_start < seg.end
    }
    if not kinds:
        return None
    if len(kinds) == 1:
        return kinds.pop()  # type: ignore[return-value]
    return "spans_both"
