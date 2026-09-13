from __future__ import annotations

import asyncio

import httpx
import pytest

from app.schemas.envelope import InputPayload
from app.tools.ingest import (
    build_raw_text_and_segments,
    ingest_input,
    normalize_for_compare,
    paste_already_in_fetched,
    segment_text,
)
from tests.conftest import assert_segments_tile

ARTICLE_BODY = (
    "Ministers announced a new coastal defence plan on Tuesday morning, "
    "citing storm damage from last winter and a three-year construction timetable."
)
PASTE_NOTE = "Journalist note: check the funding figure with Treasury."
SMART_PASTE = "The minister called it a \u201ccoastal defence plan\u2014urgent\u201d."
ASCII_BODY = (
    'The minister called it a "coastal defence plan-urgent". '
    "Further details will be published next week according to the department."
)


def _html(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html><html><head><title>"
        f"{title}</title></head><body><article><h1>{title}</h1><p>{body}</p>"
        "</article></body></html>"
    )


def _run(text: str, url: str, html: str | None = None) -> InputPayload:
    def handler(request: httpx.Request) -> httpx.Response:
        assert html is not None
        return httpx.Response(
            200,
            text=html,
            headers={"content-type": "text/html; charset=utf-8"},
            request=request,
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, follow_redirects=True)

    async def _go() -> InputPayload:
        try:
            return await ingest_input(client, text=text, url=url)
        finally:
            await client.aclose()

    return asyncio.run(_go())


def test_paste_only_tiles_raw_text() -> None:
    payload = _run(PASTE_NOTE, url="")
    assert_segments_tile(payload)
    assert payload.fetch_status == "skipped"
    assert payload.text_merged is False
    assert [s.source for s in payload.segments] == ["pasted"]
    assert payload.raw_text == PASTE_NOTE
    assert segment_text(payload, "pasted") == PASTE_NOTE
    assert segment_text(payload, "fetched") == ""


def test_url_only_tiles_raw_text() -> None:
    payload = _run("", url="https://news.example.com/coast", html=_html("Coast", ARTICLE_BODY))
    assert_segments_tile(payload)
    assert payload.fetch_status == "ok"
    assert payload.text_merged is False
    assert [s.source for s in payload.segments] == ["fetched"]
    fetched = segment_text(payload, "fetched")
    assert "coastal defence plan" in fetched.lower()
    assert segment_text(payload, "pasted") == ""
    assert payload.raw_text == fetched


def test_both_without_overlap_keeps_sources_separable() -> None:
    payload = _run(
        PASTE_NOTE,
        url="https://news.example.com/coast",
        html=_html("Coast", ARTICLE_BODY),
    )
    assert_segments_tile(payload)
    assert payload.text_merged is True
    assert [s.source for s in payload.segments] == ["pasted", "fetched"]
    pasted = segment_text(payload, "pasted")
    fetched = segment_text(payload, "fetched")
    assert pasted.startswith(PASTE_NOTE)
    assert PASTE_NOTE not in fetched
    assert payload.raw_text == pasted + fetched
    assert "coastal defence plan" in fetched.lower()
    # Layer 2 still sees one concatenated string.
    assert PASTE_NOTE in payload.raw_text
    assert fetched in payload.raw_text


def test_both_with_overlap_does_not_duplicate_paste() -> None:
    payload = _run(
        ARTICLE_BODY,
        url="https://news.example.com/coast",
        html=_html("Coast", ARTICLE_BODY),
    )
    assert_segments_tile(payload)
    assert payload.text_merged is False
    assert [s.source for s in payload.segments] == ["fetched"]
    assert segment_text(payload, "pasted") == ""
    assert ARTICLE_BODY in segment_text(payload, "fetched")
    assert payload.raw_text.count(ARTICLE_BODY) == 1


def test_smart_quotes_in_paste_match_ascii_fetched_body() -> None:
    assert paste_already_in_fetched(SMART_PASTE, ASCII_BODY)
    payload = _run(
        SMART_PASTE,
        url="https://news.example.com/quotes",
        html=_html("Quotes", ASCII_BODY),
    )
    assert_segments_tile(payload)
    assert payload.text_merged is False
    assert [s.source for s in payload.segments] == ["fetched"]
    # raw_text is the publisher body, not a mutated paste.
    assert "\u201c" not in payload.raw_text
    assert '"coastal defence plan-urgent"' in payload.raw_text


def test_normalise_does_not_mutate_raw_text() -> None:
    raw, segments = build_raw_text_and_segments(SMART_PASTE, "")
    assert raw == SMART_PASTE
    assert "\u201c" in raw
    assert normalize_for_compare(raw) != raw
    payload = InputPayload(raw_text=raw, segments=segments)
    assert_segments_tile(payload)
    assert payload.raw_text == SMART_PASTE


@pytest.mark.parametrize(
    "pasted,fetched",
    [
        (PASTE_NOTE, ""),
        ("", ARTICLE_BODY),
        (PASTE_NOTE, ARTICLE_BODY),
        (ARTICLE_BODY, ARTICLE_BODY),
        (SMART_PASTE, ASCII_BODY),
    ],
)
def test_helper_segments_always_tile(pasted: str, fetched: str) -> None:
    raw, segments = build_raw_text_and_segments(pasted, fetched)
    payload = InputPayload(raw_text=raw, segments=segments)
    assert_segments_tile(payload)
    kinds = {s.source for s in segments}
    assert payload.text_merged == ("pasted" in kinds and "fetched" in kinds)
