from __future__ import annotations

import logging
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_SECRET_QS = {
    "apikey",
    "api_key",
    "api-key",
    "key",
    "token",
    "access_token",
}

_LOGGER_NAME = "newsauth"


def setup_logging(level: str = "INFO") -> None:
    """Send NewsAuth logs to the API terminal without duplicating uvicorn's."""
    level_num = getattr(logging, (level or "INFO").upper(), logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s  %(levelname)-5s  %(message)s",
        datefmt="%H:%M:%S",
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    log = logging.getLogger(_LOGGER_NAME)
    log.setLevel(level_num)
    log.handlers.clear()
    log.addHandler(handler)
    log.propagate = False


def get_logger(suffix: str = "") -> logging.Logger:
    name = _LOGGER_NAME if not suffix else f"{_LOGGER_NAME}.{suffix}"
    return logging.getLogger(name)


def redact_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.query:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in _SECRET_QS:
            pairs.append((key, "***"))
        else:
            pairs.append((key, value))
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(pairs),
            "",
        )
    )


def short_error(exc: BaseException, limit: int = 240) -> str:
    text = str(exc).replace("\n", " ").strip()
    return text[:limit]


def http_error_detail(response) -> str:
    body = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            body = str(
                payload.get("error")
                or payload.get("message")
                or payload.get("detail")
                or payload
            )
        else:
            body = str(payload)
    except Exception:
        body = (response.text or "")[:200]
    body = redact_secrets(str(body)).replace("\n", " ")[:200]
    return f"HTTP {response.status_code} {redact_url(str(response.request.url))} {body}".strip()


def redact_secrets(text: str) -> str:
    text = re.sub(r"(sk-|hf_|AIza)[A-Za-z0-9_\-]+", r"\1***", text)
    text = re.sub(
        r"(api[-_]?key|token|authorization)([\"']?\s*[:=]\s*[\"']?)[^\"'\s&]+",
        r"\1\2***",
        text,
        flags=re.I,
    )
    return text
