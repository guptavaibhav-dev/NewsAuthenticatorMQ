from __future__ import annotations

import html as html_lib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import tldextract

from app.logutil import get_logger

log = get_logger("urls")

CanonicalSource = Literal["link_rel", "og_url", "final_url"]

TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "ref",
        "ref_src",
        "s",
        "spm",
    }
)
TRACKING_PREFIXES = ("utm_",)
REDIRECTOR_HOSTS = frozenset({"news.google.com", "t.co", "lnkd.in", "bit.ly"})
_REDIRECTOR_TARGET_KEYS = frozenset({"url", "u", "q", "redirect"})

_LINK_CANONICAL = (
    r"""<link[^>]+rel=["'][^"']*\bcanonical\b[^"']*["'][^>]+href=["']([^"']+)""",
    r"""<link[^>]+href=["']([^"']+)["'][^>]+rel=["'][^"']*\bcanonical\b[^"']*["']""",
)
_OG_URL = (
    r"""<meta[^>]+property=["']og:url["'][^>]+content=["']([^"']+)""",
    r"""<meta[^>]+content=["']([^"']+)["'][^>]+property=["']og:url["']""",
)
_PLATFORM_HOSTS_PATH = Path(__file__).resolve().parent.parent / "data" / "platform_hosts.json"


@lru_cache
def platform_hosts() -> dict[str, str]:
    """Host → identity rule map. Kept as data because the set will grow."""
    return json.loads(_PLATFORM_HOSTS_PATH.read_text(encoding="utf-8"))


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


def _host_from_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    return urlparse(raw).netloc.lower().split("@")[-1].split(":")[0]


def _subdomain_identity(url: str) -> str:
    host = _host_from_url(url)
    sub = tldextract.extract(host).subdomain
    if sub.lower().startswith("www."):
        sub = sub[4:]
    if sub.lower() == "www":
        return ""
    return sub


def _first_path_segment(url: str) -> str:
    raw = (url or "").strip()
    if raw and "://" not in raw:
        raw = f"https://{raw}"
    segments = [part for part in urlparse(raw).path.split("/") if part]
    return segments[0] if segments else ""


def _platform_match(url: str, domain: str) -> tuple[str, str] | None:
    hosts = platform_hosts()
    if domain in hosts:
        return domain, hosts[domain]
    host = _host_from_url(url).removeprefix("www.")
    matches = [
        platform
        for platform in hosts
        if host == platform or host.endswith("." + platform)
    ]
    if not matches:
        return None
    platform = max(matches, key=len)
    return platform, hosts[platform]


def publisher_identity(url: str) -> tuple[str, str, bool]:
    """Split coarse eTLD+1 from a finer platform identity.

    ``publisher_domain`` stays eTLD+1 (tldextract). For hosts in PLATFORM_HOSTS,
    ``publisher_id`` is ``<domain>/<extracted>``; otherwise it equals
    ``publisher_domain``. Cross-domain ownership grouping (bbc.com vs bbc.co.uk)
    is a later-layer concern and is intentionally not applied here. None of
    these fields rate the publisher or imply authenticity.
    """
    domain = registrable_domain(url)
    if not domain:
        return "", "", False
    matched = _platform_match(url, domain)
    if not matched:
        return domain, domain, False
    platform_domain, rule = matched
    if rule == "subdomain":
        extracted = _subdomain_identity(url)
    elif rule == "first_path_segment":
        extracted = _first_path_segment(url)
    else:
        extracted = ""
    publisher_id = f"{platform_domain}/{extracted}" if extracted else domain
    return domain, publisher_id, True


def unwrap_redirector(url: str) -> str:
    """Return an in-URL redirect target for known wrappers, else `url`.

    Follows news.google.com / t.co / lnkd.in / bit.ly only when the destination
    is already present as a query parameter. HTTP hops are resolved by ingest,
    not here. This is URL hygiene, not a judgement of the destination.
    """
    raw = (url or "").strip()
    if not raw:
        return raw
    parsed = urlparse(raw)
    host = parsed.netloc.lower().removeprefix("www.")
    if host not in REDIRECTOR_HOSTS:
        return raw
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in _REDIRECTOR_TARGET_KEYS and value.startswith("http"):
            return value
    return raw


def _is_tracking_param(key: str) -> bool:
    lowered = (key or "").lower()
    if lowered.startswith(TRACKING_PREFIXES):
        return True
    return lowered in TRACKING_PARAMS


def _strip_amp_wrappers(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    path = parsed.path or ""
    scheme = parsed.scheme or "https"
    host_bare = host.removeprefix("www.")

    if host_bare == "google.com" and path.lower().startswith("/amp/"):
        rest = path[5:]
        if rest.lower().startswith("s/"):
            rest = rest[2:]
        if rest:
            return f"{scheme}://{rest}"

    if host.endswith("cdn.ampproject.org"):
        match = re.match(r"^/[cv]/(?:s/)?(.+)$", path)
        if match:
            return f"{scheme}://{match.group(1)}"

    stripped_path = re.sub(r"/amp(?:\.html)?/?$", "", path, flags=re.I)
    if stripped_path != path:
        return urlunparse(parsed._replace(path=stripped_path))
    return url


def _strip_tracking_and_normalize(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().split("@")[-1]
    if ":" in host and not host.endswith("]"):
        name, port = host.rsplit(":", 1)
        host = f"{name.removeprefix('www.')}:{port}" if port and port not in {"80", "443"} else name.removeprefix("www.")
    else:
        host = host.removeprefix("www.")
    path = parsed.path.rstrip("/")
    scheme = parsed.scheme or "https"
    kept = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not _is_tracking_param(k)]
    kept.sort(key=lambda kv: (kv[0].lower(), kv[0], kv[1]))
    query = urlencode(kept, doseq=True)
    return urlunparse((scheme, host, path, "", query, ""))


def canonical_url(url: str) -> str:
    """Normalise a URL without fetching.

    Unwraps in-URL redirector targets, strips Google AMP wrappers and `/amp`
    suffixes, drops tracking params and the fragment, lowercases the host,
    strips `www.` and a trailing slash, and sorts remaining query params.
    Path case is preserved. This is a stable key for dedup, not a statement
    that the resource is the publisher's preferred page or that it is authentic.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    unwrapped = unwrap_redirector(raw)
    return _strip_tracking_and_normalize(_strip_amp_wrappers(unwrapped))


def _first_attr(html: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, html or "", re.I)
        if not match:
            continue
        value = html_lib.unescape(match.group(1)).strip()
        if value:
            return value
    return None


def _accepted_declared_url(declared: str | None, final_url: str, source: CanonicalSource) -> str | None:
    if not declared:
        return None
    resolved = urljoin(final_url, declared)
    if not resolved.startswith("http"):
        return None
    if registrable_domain(resolved) != registrable_domain(final_url):
        log.warning(
            "rejected publisher %s %s: registrable domain %s does not match final URL %s (%s). "
            "Falling through; this is not a falsity signal.",
            source,
            resolved,
            registrable_domain(resolved) or "(none)",
            registrable_domain(final_url) or "(none)",
            final_url,
        )
        return None
    return resolved


def resolve_canonical_url(html: str | None, final_url: str) -> tuple[str, CanonicalSource]:
    """Choose a canonical URL from fetched HTML, then the post-redirect URL.

    Precedence (first accepted hit wins):
      1. ``<link rel="canonical">`` href
      2. ``og:url``
      3. the final URL after redirects

    Options 1 and 2 are publisher-declared and attacker-controllable. They are
    accepted only when their registrable domain matches the final URL's.
    Otherwise the next option is used. The returned URL is passed through
    ``canonical_url`` (tracking/AMP/fragment hygiene). This is identity for
    dedup, not an authenticity score.
    """
    base = unwrap_redirector((final_url or "").strip())
    page = html or ""
    for source, patterns in (("link_rel", _LINK_CANONICAL), ("og_url", _OG_URL)):
        accepted = _accepted_declared_url(_first_attr(page, patterns), base, source)
        if accepted:
            return canonical_url(accepted), source
    return canonical_url(base), "final_url"


def normalize_title(title: str) -> str:
    return " ".join(
        "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in title).split()
    )
