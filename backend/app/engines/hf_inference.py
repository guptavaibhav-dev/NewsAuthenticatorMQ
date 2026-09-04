from __future__ import annotations

import asyncio

import httpx

from app.logutil import get_logger, http_error_detail

log = get_logger("hf")

HF_INFERENCE_BASE = "https://router.huggingface.co/hf-inference"

# Hosts that failed DNS/connect this process. api-inference.huggingface.co is gone.
_SKIP_HOSTS: set[str] = set()


def _urls_for(model: str, pipeline: str | None) -> list[str]:
    urls: list[str] = []
    if pipeline:
        urls.append(f"{HF_INFERENCE_BASE}/models/{model}/pipeline/{pipeline}")
        urls.append(f"{HF_INFERENCE_BASE}/pipeline/{pipeline}/{model}")
    urls.append(f"{HF_INFERENCE_BASE}/models/{model}")
    return urls


async def hf_infer(
    client: httpx.AsyncClient,
    token: str,
    model: str,
    payload: dict,
    *,
    timeout_s: float = 60.0,
    pipeline: str | None = None,
) -> object:
    """Call Hugging Face Inference via the current router."""
    timeout = httpx.Timeout(timeout_s, connect=15.0)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    urls = [url for url in _urls_for(model, pipeline) if not _host_skipped(url)]
    if not urls:
        raise RuntimeError(f"Hugging Face inference has no reachable endpoint for {model}")

    last_error: Exception | None = None
    for url in urls:
        try:
            return await _post_json(client, url, headers, payload, timeout)
        except httpx.HTTPStatusError as exc:
            detail = http_error_detail(exc.response)
            last_error = RuntimeError(detail)
            code = exc.response.status_code
            if code in {404, 410, 400} and url != urls[-1]:
                log.warning("hf %s failed (%s); trying next endpoint", url, code)
                continue
            raise RuntimeError(detail) from exc
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            last_error = exc
            _remember_bad_host(url)
            if url != urls[-1]:
                log.warning("hf %s failed: %s; trying next endpoint", url, exc)
                continue
            raise RuntimeError(str(exc)) from exc
        except Exception as exc:
            last_error = exc
            if "getaddrinfo failed" in str(exc) or "Name or service not known" in str(exc):
                _remember_bad_host(url)
            if url != urls[-1]:
                log.warning("hf %s failed: %s; trying next endpoint", url, exc)
                continue
            raise
    if last_error:
        raise last_error
    raise RuntimeError(f"Hugging Face inference failed for {model}")


def _host_of(url: str) -> str:
    if "://" not in url:
        return ""
    return url.split("/")[2]


def _host_skipped(url: str) -> bool:
    return _host_of(url) in _SKIP_HOSTS


def _remember_bad_host(url: str) -> None:
    host = _host_of(url)
    if host:
        _SKIP_HOSTS.add(host)


async def _post_json(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    payload: dict,
    timeout: httpx.Timeout,
) -> object:
    response = await client.post(url, headers=headers, json=payload, timeout=timeout)
    if response.status_code == 503:
        wait = 10.0
        try:
            body = response.json()
            if isinstance(body, dict):
                wait = min(float(body.get("estimated_time") or 10), 25.0)
        except Exception:
            pass
        log.info("hf model loading; waiting %.0fs then retry", wait)
        await asyncio.sleep(wait)
        response = await client.post(url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(str(data.get("error")))
    return data
