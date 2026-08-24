from __future__ import annotations

from urllib.parse import urlparse

import tldextract


def registrable_domain(url_or_host: str) -> str:
    raw = (url_or_host or "").strip()
    if not raw:
        return ""
    host = raw
    if "://" in raw:
        host = urlparse(raw).netloc
    host = host.lower().split("@")[-1].split(":")[0]
    extracted = tldextract.extract(host)
    if not extracted.domain:
        return host.removeprefix("www.")
    return f"{extracted.domain}.{extracted.suffix}".rstrip(".")


def canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    scheme = parsed.scheme or "https"
    return f"{scheme}://{host}{path}"


def normalize_title(title: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in title).split())
