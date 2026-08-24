from __future__ import annotations

from app.schemas.envelope import SourceBand
from app.scoring.urls import registrable_domain

# Independence is counted by family, not by URL.
PUBLISHER_FAMILIES: dict[str, str] = {
    "bbc.co.uk": "bbc",
    "bbc.com": "bbc",
    "theguardian.com": "guardian",
    "guardian.co.uk": "guardian",
    "nytimes.com": "nyt",
    "reuters.com": "reuters",
    "apnews.com": "ap",
    "ap.org": "ap",
    "abc.net.au": "abc_au",
    "smh.com.au": "nine_au",
    "theage.com.au": "nine_au",
    "afr.com": "nine_au",
    "cnn.com": "cnn",
    "edition.cnn.com": "cnn",
    "washingtonpost.com": "wapo",
    "wsj.com": "wsj",
    "ft.com": "ft",
    "aljazeera.com": "aljazeera",
    "theage.com": "nine_au",
    "news.com.au": "news_corp_au",
    "theaustralian.com.au": "news_corp_au",
    "foxnews.com": "fox",
    "nbcnews.com": "nbc",
    "cbsnews.com": "cbs",
    "abcnews.go.com": "abc_us",
    "npr.org": "npr",
    "politico.com": "politico",
    "bloomberg.com": "bloomberg",
}

KNOWN_LEGACY = {
    "bbc",
    "guardian",
    "nyt",
    "reuters",
    "ap",
    "abc_au",
    "wapo",
    "wsj",
    "ft",
    "aljazeera",
    "npr",
    "bloomberg",
    "abc_us",
    "nbc",
    "cbs",
}

AGGREGATOR_DOMAINS = {
    "news.google.com",
    "news.yahoo.com",
    "msn.com",
    "apple.news",
    "flipboard.com",
}


def publisher_family(url_or_domain: str) -> str:
    domain = registrable_domain(url_or_domain)
    if domain in PUBLISHER_FAMILIES:
        return PUBLISHER_FAMILIES[domain]
    host = domain
    if url_or_domain.startswith("http"):
        from urllib.parse import urlparse

        host = urlparse(url_or_domain).netloc.lower().removeprefix("www.")
    if host in PUBLISHER_FAMILIES:
        return PUBLISHER_FAMILIES[host]
    return domain or "unknown"


def source_band(url_or_domain: str) -> SourceBand:
    domain = registrable_domain(url_or_domain)
    host = domain
    if "google.com" in domain or domain in AGGREGATOR_DOMAINS:
        return "aggregator"
    family = publisher_family(url_or_domain)
    if family in KNOWN_LEGACY:
        return "known_legacy"
    if host in AGGREGATOR_DOMAINS:
        return "aggregator"
    return "unknown"


def independent_family_count(urls: list[str]) -> int:
    families = {publisher_family(url) for url in urls if url}
    families.discard("")
    families.discard("unknown")
    return len(families)
