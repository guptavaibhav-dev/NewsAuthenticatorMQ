"""Layer 3 source adapters, each declaring what it can and cannot reach."""

from __future__ import annotations

from app.config import Settings
from app.retrieval.adapters.base import (
    AdapterError,
    ArticleContext,
    SourceAdapter,
    build_hit,
    detect_wire_credit,
)
from app.retrieval.adapters.factcheck import GoogleFactCheckAdapter
from app.retrieval.adapters.gdelt import GdeltAdapter
from app.retrieval.adapters.gnews import GNewsAdapter
from app.retrieval.adapters.guardian import GuardianAdapter
from app.retrieval.adapters.newsapi import NewsApiAdapter
from app.retrieval.adapters.newsdata import NewsdataAdapter
from app.retrieval.adapters.wikipedia import WikipediaAdapter

__all__ = [
    "AdapterError",
    "ArticleContext",
    "GNewsAdapter",
    "GdeltAdapter",
    "GoogleFactCheckAdapter",
    "GuardianAdapter",
    "NewsApiAdapter",
    "NewsdataAdapter",
    "SourceAdapter",
    "WikipediaAdapter",
    "build_hit",
    "detect_wire_credit",
    "news_adapters",
]


def news_adapters(settings: Settings) -> list[SourceAdapter]:
    """Every article-search adapter, in the order they should be tried.

    All of them are returned whether or not they have a key. An unconfigured
    adapter still reports skipped_no_key, because a source that was never asked
    has to be visible in the coverage report rather than silently absent.
    """
    return [
        GuardianAdapter.from_settings(settings),
        NewsApiAdapter.from_settings(settings),
        GNewsAdapter.from_settings(settings),
        NewsdataAdapter.from_settings(settings),
        GdeltAdapter.from_settings(settings),
    ]
