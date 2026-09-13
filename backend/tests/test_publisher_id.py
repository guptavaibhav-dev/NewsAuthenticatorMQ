from __future__ import annotations

from app.scoring.urls import platform_hosts, publisher_identity, registrable_domain

CASES = [
    (
        "substack_subdomain",
        "https://vaibhav.substack.com/p/hello",
        "substack.com",
        "substack.com/vaibhav",
        True,
    ),
    (
        "medium_first_path_segment",
        "https://medium.com/@alice/a-story-title-abc123",
        "medium.com",
        "medium.com/@alice",
        True,
    ),
    (
        "wordpress_subdomain",
        "https://myblog.wordpress.com/2024/01/01/post",
        "wordpress.com",
        "wordpress.com/myblog",
        True,
    ),
    (
        "blogspot_subdomain",
        "https://myblog.blogspot.com/2024/01/post.html",
        "blogspot.com",
        "blogspot.com/myblog",
        True,
    ),
    (
        "github_pages_subdomain",
        "https://octocat.github.io/notes/",
        "github.io",
        "github.io/octocat",
        True,
    ),
    (
        "x_first_path_segment",
        "https://x.com/reuters/status/123",
        "x.com",
        "x.com/reuters",
        True,
    ),
    (
        "ordinary_publisher_unchanged",
        "https://www.bbc.com/news/world-123",
        "bbc.com",
        "bbc.com",
        False,
    ),
    (
        "bbc_co_uk_not_grouped_with_bbc_com",
        "https://www.bbc.co.uk/news/uk-123",
        "bbc.co.uk",
        "bbc.co.uk",
        False,
    ),
    (
        "platform_without_extracted_identity",
        "https://medium.com/",
        "medium.com",
        "medium.com",
        True,
    ),
]


def test_platform_hosts_is_a_data_file() -> None:
    hosts = platform_hosts()
    assert hosts["substack.com"] == "subdomain"
    assert hosts["medium.com"] == "first_path_segment"
    assert hosts["x.com"] == "first_path_segment"


def test_publisher_identity_table() -> None:
    for name, url, domain, publisher_id, is_platform in CASES:
        got_domain, got_id, got_platform = publisher_identity(url)
        assert got_domain == domain, name
        assert got_id == publisher_id, name
        assert got_platform is is_platform, name
        assert registrable_domain(url) == domain, name
