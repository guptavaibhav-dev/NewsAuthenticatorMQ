from __future__ import annotations

import logging

import pytest

from app.scoring.urls import canonical_url, resolve_canonical_url


CASES = [
    (
        "link_rel_wins_over_og_and_final",
        '<link rel="canonical" href="https://www.example.com/clean">'
        '<meta property="og:url" content="https://www.example.com/og">',
        "https://www.example.com/dirty?utm_source=share",
        "https://example.com/clean",
        "link_rel",
    ),
    (
        "href_before_rel_canonical",
        '<link href="https://example.com/href-first" rel="canonical">',
        "https://example.com/other",
        "https://example.com/href-first",
        "link_rel",
    ),
    (
        "og_url_when_no_canonical",
        '<meta property="og:url" content="https://example.com/og-page">',
        "https://example.com/final-page",
        "https://example.com/og-page",
        "og_url",
    ),
    (
        "final_url_when_no_declarations",
        "<html><title>No hints</title></html>",
        "https://example.com/story/",
        "https://example.com/story",
        "final_url",
    ),
    (
        "hostile_canonical_rejected",
        '<link rel="canonical" href="https://evil.test/phishing">',
        "https://news.example.com/real-story",
        "https://news.example.com/real-story",
        "final_url",
    ),
    (
        "hostile_canonical_falls_through_to_og",
        '<link rel="canonical" href="https://evil.test/phishing">'
        '<meta property="og:url" content="https://news.example.com/og">',
        "https://news.example.com/real-story",
        "https://news.example.com/og",
        "og_url",
    ),
    (
        "hostile_og_rejected_after_hostile_canonical",
        '<link rel="canonical" href="https://evil.test/phishing">'
        '<meta property="og:url" content="https://also-evil.test/bait">',
        "https://news.example.com/real-story",
        "https://news.example.com/real-story",
        "final_url",
    ),
    (
        "relative_canonical_resolved_against_final",
        '<link rel="canonical" href="/clean-path">',
        "https://www.example.com/dirty?utm_medium=email",
        "https://example.com/clean-path",
        "link_rel",
    ),
    (
        "strips_tracking_params_keeps_others_sorted",
        "",
        "https://example.com/a?z=1&utm_source=x&utm_campaign=y&fbclid=1&gclid=2"
        "&igshid=3&mc_cid=4&mc_eid=5&ref=tw&ref_src=twsrc&s=1&spm=2&keep=yes&a=2",
        "https://example.com/a?a=2&keep=yes&z=1",
        "final_url",
    ),
    (
        "drops_fragment",
        "",
        "https://example.com/a#section",
        "https://example.com/a",
        "final_url",
    ),
    (
        "preserves_path_case",
        "",
        "https://example.com/News/ABC",
        "https://example.com/News/ABC",
        "final_url",
    ),
    (
        "unwraps_google_news_url_param",
        "",
        "https://news.google.com/rss/articles/CBMi?url=https://www.bbc.com/news/x&oc=5",
        "https://bbc.com/news/x",
        "final_url",
    ),
    (
        "strips_amp_path_suffix",
        "",
        "https://example.com/story/amp",
        "https://example.com/story",
        "final_url",
    ),
    (
        "strips_google_amp_wrapper",
        "",
        "https://www.google.com/amp/s/www.example.com/story?utm_source=amp",
        "https://example.com/story",
        "final_url",
    ),
    (
        "strips_www_and_trailing_slash",
        "",
        "https://www.example.com/story/",
        "https://example.com/story",
        "final_url",
    ),
]


@pytest.mark.parametrize(
    "name,html,final_url,expected_url,expected_source",
    CASES,
    ids=[row[0] for row in CASES],
)
def test_canonical_resolution_rules(
    name: str,
    html: str,
    final_url: str,
    expected_url: str,
    expected_source: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    got_url, got_source = resolve_canonical_url(html, final_url)
    assert got_url == expected_url
    assert got_source == expected_source
    if "hostile" in name:
        assert "rejected publisher" in caplog.text
        assert "not a falsity signal" in caplog.text


def test_canonical_url_is_stable_across_share_variants() -> None:
    a = canonical_url("https://www.example.com/story/?utm_source=twitter&fbclid=abc#top")
    b = canonical_url("https://example.com/story?ref=home")
    assert a == b == "https://example.com/story"
