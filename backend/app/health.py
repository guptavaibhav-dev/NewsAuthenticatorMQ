from __future__ import annotations

import asyncio
from typing import Any, Literal

import httpx

from app.config import Settings
from app.logutil import get_logger

log = get_logger("health")

KeyStatus = Literal["working", "configured", "missing", "error"]
LayerStatus = Literal["ready", "degraded", "unavailable"]


def utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


async def build_health(
    settings: Settings,
    client: httpx.AsyncClient | None,
    *,
    probe: bool,
) -> dict[str, Any]:
    keys = await _key_reports(settings, client, probe=probe)
    by_id = {row["id"]: row for row in keys}
    if probe:
        for row in keys:
            line = f"key {row['env']}  {row['status']}  {row['detail']}"
            if row["status"] == "error":
                log.error(line)
            elif row["status"] == "missing":
                log.warning(line)
            else:
                log.info(line)

    engines = _engines(settings, by_id)
    services = _services(by_id)
    modules = _modules(by_id)
    layers = _layers(by_id, settings)

    working_keys = sum(1 for k in keys if k["status"] == "working")
    configured_keys = sum(1 for k in keys if k["configured"])
    ready_layers = sum(1 for layer in layers if layer["status"] == "ready")

    return {
        "ok": True,
        "probed": probe,
        "checked_at": utc_now_iso(),
        "summary": {
            "keys_working": working_keys,
            "keys_configured": configured_keys,
            "keys_total": len(keys),
            "layers_ready": ready_layers,
            "layers_total": len(layers),
        },
        "keys": keys,
        "engines": engines,
        "services": services,
        "modules": modules,
        "layers": layers,
        "models": {
            "preprocess": settings.preprocess_model,
            "query_planner": settings.query_planner_model,
            "evidence_llm": settings.evidence_llm_model,
            "uncertainty": settings.uncertainty_model,
            "documentation": settings.documentation_model,
            "nli": settings.nli_model,
            "ner": settings.ner_model,
            "embedding": settings.embedding_model,
        },
        "providers": {
            "openai": bool(settings.openai_api_key),
            "anthropic": bool(settings.anthropic_api_key),
            "gemini": bool(settings.gemini_key),
            "newsapi": bool(settings.newsapi_key),
            "guardian": bool(settings.guardian_api_key),
            "gnews": bool(settings.gnews_api_key or settings.newsdata_api_key),
            "factcheck": bool(settings.factcheck_key),
            "huggingface": bool(settings.hf_token),
        },
    }


async def _key_reports(
    settings: Settings,
    client: httpx.AsyncClient | None,
    *,
    probe: bool,
) -> list[dict[str, Any]]:
    specs = [
        {
            "id": "openai",
            "env": "OPENAI_API_KEY",
            "label": "OpenAI",
            "used_by": ["Pre-processing (GPT-4.1)", "Uncertainty (o-series / GPT)"],
            "present": bool(settings.openai_api_key),
            "probe": lambda: _probe_openai(client, settings.openai_api_key),
        },
        {
            "id": "anthropic",
            "env": "ANTHROPIC_API_KEY",
            "label": "Anthropic",
            "used_by": ["Verification query planner (Claude)", "Documentation (Claude)"],
            "present": bool(settings.anthropic_api_key),
            "probe": lambda: _probe_anthropic(client, settings.anthropic_api_key),
        },
        {
            "id": "gemini",
            "env": "GEMINI_API_KEY",
            "label": "Gemini (AI Studio)",
            "used_by": ["Evidence analysis (Gemini 3.6 Flash)"],
            "present": bool(settings.gemini_api_key or settings.google_api_key),
            "probe": lambda: _probe_gemini(client, settings.gemini_key),
        },
        {
            "id": "google",
            "env": "GOOGLE_API_KEY",
            "label": "Google Cloud (fallback)",
            "used_by": ["Optional fallback for Gemini and Fact Check"],
            "present": bool(settings.google_api_key),
            "probe": lambda: _probe_gemini(client, settings.google_api_key),
        },
        {
            "id": "newsapi",
            "env": "NEWSAPI_KEY",
            "label": "NewsAPI",
            "used_by": ["Verification: existence and similar coverage"],
            "present": bool(settings.newsapi_key),
            "probe": lambda: _probe_newsapi(client, settings.newsapi_key),
        },
        {
            "id": "guardian",
            "env": "GUARDIAN_API_KEY",
            "label": "The Guardian",
            "used_by": ["Verification: trusted-corpus search"],
            "present": bool(settings.guardian_api_key),
            "probe": lambda: _probe_guardian(client, settings.guardian_api_key),
        },
        {
            "id": "gnews",
            "env": "GNEWS_API_KEY",
            "label": "GNews",
            "used_by": ["Verification: second aggregator"],
            "present": bool(settings.gnews_api_key),
            "probe": lambda: _probe_gnews(client, settings.gnews_api_key),
        },
        {
            "id": "newsdata",
            "env": "NEWSDATA_API_KEY",
            "label": "NewsData.io",
            "used_by": ["Verification: second aggregator (if GNews unset)"],
            "present": bool(settings.newsdata_api_key),
            "probe": lambda: _probe_newsdata(client, settings.newsdata_api_key),
        },
        {
            "id": "factcheck",
            "env": "FACTCHECK_API_KEY",
            "label": "Google Fact Check",
            "used_by": ["Verification: prior ClaimReview search"],
            "present": bool(settings.factcheck_key),
            "probe": lambda: _probe_factcheck(client, settings.factcheck_key),
        },
        {
            "id": "huggingface",
            "env": "HF_TOKEN",
            "label": "Hugging Face",
            "used_by": ["NER", "DeBERTa NLI", "Embeddings"],
            "present": bool(settings.hf_token),
            "probe": lambda: _probe_hf(client, settings.hf_token),
        },
    ]

    async def one(spec: dict[str, Any]) -> dict[str, Any]:
        present = spec["present"]
        if not present:
            return _key_row(spec, configured=False, status="missing", detail="Not set in backend/.env")
        if not probe or client is None:
            return _key_row(spec, configured=True, status="configured", detail="Present; live probe not run")
        try:
            ok, detail = await spec["probe"]()
            return _key_row(
                spec,
                configured=True,
                status="working" if ok else "error",
                detail=detail,
            )
        except Exception as exc:
            return _key_row(spec, configured=True, status="error", detail=str(exc)[:180])

    return await asyncio.gather(*[one(spec) for spec in specs])


def _key_row(spec: dict[str, Any], *, configured: bool, status: KeyStatus, detail: str) -> dict[str, Any]:
    return {
        "id": spec["id"],
        "env": spec["env"],
        "label": spec["label"],
        "used_by": spec["used_by"],
        "configured": configured,
        "status": status,
        "detail": detail,
    }


async def _probe_openai(client: httpx.AsyncClient | None, key: str) -> tuple[bool, str]:
    assert client is not None
    response = await client.get(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {key}"},
    )
    if response.status_code == 200:
        return True, "OpenAI models endpoint accepted the key"
    return False, f"HTTP {response.status_code}"


async def _probe_anthropic(client: httpx.AsyncClient | None, key: str) -> tuple[bool, str]:
    assert client is not None
    response = await client.get(
        "https://api.anthropic.com/v1/models",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    if response.status_code == 200:
        return True, "Anthropic models endpoint accepted the key"
    return False, f"HTTP {response.status_code}"


async def _probe_gemini(client: httpx.AsyncClient | None, key: str) -> tuple[bool, str]:
    assert client is not None
    if not key:
        return False, "No Gemini/Google key"
    response = await client.get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        params={"key": key},
    )
    if response.status_code == 200:
        return True, "Gemini models list accepted the key"
    return False, f"HTTP {response.status_code}"


async def _probe_newsapi(client: httpx.AsyncClient | None, key: str) -> tuple[bool, str]:
    assert client is not None
    response = await client.get(
        "https://newsapi.org/v2/top-headlines",
        params={"country": "us", "pageSize": 1, "apiKey": key},
    )
    if response.status_code == 200:
        return True, "NewsAPI responded"
    message = ""
    try:
        message = str((response.json() or {}).get("message") or "")
    except Exception:
        message = response.text[:80]
    return False, f"HTTP {response.status_code}: {message}".strip()[:180]


async def _probe_guardian(client: httpx.AsyncClient | None, key: str) -> tuple[bool, str]:
    assert client is not None
    response = await client.get(
        "https://content.guardianapis.com/search",
        params={"q": "news", "page-size": 1, "api-key": key},
    )
    if response.status_code == 200:
        return True, "Guardian Open Platform responded"
    return False, f"HTTP {response.status_code}"


async def _probe_gnews(client: httpx.AsyncClient | None, key: str) -> tuple[bool, str]:
    assert client is not None
    response = await client.get(
        "https://gnews.io/api/v4/search",
        params={"q": "news", "max": 1, "token": key, "lang": "en"},
    )
    if response.status_code == 200:
        return True, "GNews responded"
    return False, f"HTTP {response.status_code}"


async def _probe_newsdata(client: httpx.AsyncClient | None, key: str) -> tuple[bool, str]:
    assert client is not None
    response = await client.get(
        "https://newsdata.io/api/1/latest",
        params={"apikey": key, "q": "news", "language": "en"},
    )
    if response.status_code == 200:
        return True, "NewsData.io responded"
    return False, f"HTTP {response.status_code}"


async def _probe_factcheck(client: httpx.AsyncClient | None, key: str) -> tuple[bool, str]:
    assert client is not None
    response = await client.get(
        "https://factchecktools.googleapis.com/v1alpha1/claims:search",
        params={"query": "climate", "pageSize": 1, "key": key, "languageCode": "en"},
    )
    if response.status_code == 200:
        return True, "Fact Check Tools Claim Search responded"
    return False, f"HTTP {response.status_code}"


async def _probe_hf(client: httpx.AsyncClient | None, key: str) -> tuple[bool, str]:
    assert client is not None
    response = await client.get(
        "https://huggingface.co/api/whoami-v2",
        headers={"Authorization": f"Bearer {key}"},
    )
    if response.status_code == 200:
        name = (response.json() or {}).get("name") or "ok"
        return True, f"Hugging Face token valid ({name})"
    return False, f"HTTP {response.status_code}"


def _status_of(by_id: dict[str, dict], key_id: str) -> str:
    row = by_id.get(key_id) or {}
    return row.get("status") or "missing"


def _ok(status: str) -> bool:
    return status in {"working", "configured"}


def _engines(settings: Settings, by_id: dict[str, dict]) -> list[dict[str, Any]]:
    return [
        _engine("gpt-4.1", "Pre-processing LLM", settings.preprocess_model, "openai", by_id),
        _engine("ner", "Independent NER", settings.ner_model, "huggingface", by_id, fallback=True),
        _engine("claude-planner", "Verification query planner", settings.query_planner_model, "anthropic", by_id, fallback=True),
        _engine("deberta-nli", "Evidence NLI (non-generative)", settings.nli_model, "huggingface", by_id, fallback=True),
        _engine("embeddings", "Similarity / near-duplicate", settings.embedding_model, "huggingface", by_id, fallback=True),
        _engine("gemini-analyst", "Blinded evidence analyst", settings.evidence_llm_model, "gemini", by_id),
        _engine("fusion", "Deterministic corroboration fusion", "local rules", None, by_id, always="working"),
        _engine("uncertainty-llm", "Uncertainty / risk", settings.uncertainty_model, "openai", by_id, fallback=True),
        _engine("documentation-llm", "Verification record", settings.documentation_model, "anthropic", by_id, fallback=True),
        _engine("editorial", "Human editorial decision", "dashboard (no model)", None, by_id, always="working"),
    ]


def _engine(
    id_: str,
    role: str,
    model: str,
    key_id: str | None,
    by_id: dict[str, dict],
    *,
    fallback: bool = False,
    always: str | None = None,
) -> dict[str, Any]:
    if always:
        status = always
        detail = "Always available locally"
    elif key_id is None:
        status = "working"
        detail = "No external key required"
    else:
        ks = _status_of(by_id, key_id)
        if ks == "working":
            status = "working"
            detail = f"Backed by {key_id} key"
        elif ks == "configured":
            status = "configured"
            detail = f"{key_id} key present"
        elif fallback:
            status = "fallback"
            detail = f"{key_id} unavailable; local fallback will run"
        else:
            status = "unavailable" if ks == "missing" else "error"
            detail = f"Needs a working {key_id} key"
    return {
        "id": id_,
        "role": role,
        "model": model,
        "key": key_id,
        "status": status,
        "detail": detail,
    }


def _services(by_id: dict[str, dict]) -> list[dict[str, Any]]:
    wiki = {
        "id": "wikipedia",
        "label": "Wikipedia / Wikidata",
        "kind": "Verification tool (no key)",
        "status": "working",
        "detail": "Public MediaWiki API; no API key",
        "key": None,
    }
    return [
        _service("newsapi", "NewsAPI.org", "Verification tool", by_id),
        _service("guardian", "Guardian Open Platform", "Verification tool", by_id),
        _service("gnews", "GNews", "Verification tool", by_id),
        _service("newsdata", "NewsData.io", "Verification tool", by_id),
        _service("factcheck", "Google Fact Check Tools", "Verification tool", by_id),
        wiki,
        _service("huggingface", "Hugging Face Inference", "NLI / NER / embeddings", by_id),
        _service("openai", "OpenAI API", "LLM provider", by_id),
        _service("anthropic", "Anthropic API", "LLM provider", by_id),
        _service("gemini", "Gemini API", "LLM provider", by_id),
    ]


def _service(key_id: str, label: str, kind: str, by_id: dict[str, dict]) -> dict[str, Any]:
    row = by_id.get(key_id) or {}
    return {
        "id": key_id,
        "label": label,
        "kind": kind,
        "status": row.get("status") or "missing",
        "detail": row.get("detail") or "",
        "key": row.get("env"),
    }


def _modules(by_id: dict[str, dict]) -> list[dict[str, Any]]:
    return [
        {
            "id": "ingest",
            "label": "URL / text ingest",
            "layer": "Input",
            "status": "working",
            "detail": "trafilatura fetch; no vendor key",
        },
        {
            "id": "claim-extract",
            "label": "Claim extraction",
            "layer": "Pre-processing",
            "status": _module_status(by_id, "openai", fallback=True),
            "detail": "GPT-4.1, heuristic fallback if key missing",
        },
        {
            "id": "query-planner",
            "label": "Search query planner",
            "layer": "Retrieval and Independence",
            "status": _module_status(by_id, "anthropic", fallback=True),
            "detail": "Claude, deterministic queries if key missing",
        },
        {
            "id": "existence",
            "label": "Existence / similar-article match",
            "layer": "Retrieval and Independence",
            "status": _any_news_status(by_id),
            "detail": "NewsAPI + Guardian + aggregator + embeddings",
        },
        {
            "id": "nli",
            "label": "Claim–evidence NLI",
            "layer": "Evidence Analysis",
            "status": _module_status(by_id, "huggingface", fallback=True),
            "detail": "DeBERTa via HF, lexical fallback if token missing",
        },
        {
            "id": "gemini-analyst",
            "label": "Blinded multi-document analyst",
            "layer": "Evidence Analysis",
            "status": _module_status(by_id, "gemini", fallback=False),
            "detail": "Skipped if Gemini key is not working",
        },
        {
            "id": "fusion",
            "label": "Deterministic fusion",
            "layer": "Evidence Analysis",
            "status": "working",
            "detail": "Local corroboration rules; no key",
        },
        {
            "id": "uncertainty",
            "label": "Uncertainty scoring",
            "layer": "Uncertainty and Risk",
            "status": _module_status(by_id, "openai", fallback=True),
            "detail": "Rule-based fallback if OpenAI unavailable",
        },
        {
            "id": "documentation",
            "label": "Verification record",
            "layer": "Output and Documentation",
            "status": _module_status(by_id, "anthropic", fallback=True),
            "detail": "Template fallback if Claude unavailable",
        },
        {
            "id": "editorial",
            "label": "Journalist decision control",
            "layer": "Human Editorial Decision",
            "status": "working",
            "detail": "Dashboard only; no model",
        },
    ]


def _module_status(by_id: dict[str, dict], key_id: str, *, fallback: bool) -> str:
    status = _status_of(by_id, key_id)
    if status in {"working", "configured"}:
        return status if status == "working" else "configured"
    if fallback:
        return "fallback"
    return "unavailable" if status == "missing" else "error"


def _any_news_status(by_id: dict[str, dict]) -> str:
    news = [_status_of(by_id, k) for k in ("newsapi", "guardian", "gnews", "newsdata")]
    if any(s == "working" for s in news):
        return "working"
    if any(s == "configured" for s in news):
        return "configured"
    if any(s == "error" for s in news):
        return "error"
    return "unavailable"


def _layers(by_id: dict[str, dict], settings: Settings) -> list[dict[str, Any]]:
    news = _any_news_status(by_id)
    openai = _status_of(by_id, "openai")
    anthropic = _status_of(by_id, "anthropic")
    gemini = _status_of(by_id, "gemini")
    hf = _status_of(by_id, "huggingface")
    factcheck = _status_of(by_id, "factcheck")

    return [
        {
            "id": "input",
            "order": 1,
            "label": "Input",
            "status": "ready",
            "detail": "Text and URL intake are local. Wikipedia grounding needs no key.",
            "depends_on": ["ingest", "wikipedia"],
        },
        {
            "id": "preprocess",
            "order": 2,
            "label": "Pre-processing and Classification",
            "status": _layer_status(preferred=openai, fallback=True),
            "detail": (
                f"Engine: {settings.preprocess_model} + NER. "
                + _layer_note(openai, "OpenAI", has_fallback=True)
            ),
            "depends_on": ["OPENAI_API_KEY", "HF_TOKEN (optional NER)"],
        },
        {
            "id": "verification",
            "order": 3,
            "label": "Retrieval and Independence",
            "status": _verification_layer(news, anthropic, factcheck),
            "detail": (
                f"Planner: {settings.query_planner_model}. "
                + _layer_note(news, "news portals", has_fallback=False)
                + " "
                + _layer_note(anthropic, "Claude planner", has_fallback=True)
            ),
            "depends_on": ["NEWSAPI_KEY", "GUARDIAN_API_KEY", "GNEWS_API_KEY", "FACTCHECK_API_KEY"],
        },
        {
            "id": "evidence",
            "order": 4,
            "label": "Evidence Analysis",
            "status": _evidence_layer(hf, gemini),
            "detail": (
                f"NLI: {settings.nli_model}. Analyst: {settings.evidence_llm_model}. "
                + _layer_note(hf, "Hugging Face NLI", has_fallback=True)
                + " "
                + _layer_note(gemini, "Gemini analyst", has_fallback=False)
            ),
            "depends_on": ["HF_TOKEN", "GEMINI_API_KEY"],
        },
        {
            "id": "uncertainty",
            "order": 5,
            "label": "Uncertainty and Risk Assessment",
            "status": _layer_status(preferred=openai, fallback=True),
            "detail": (
                f"Engine: {settings.uncertainty_model}. "
                + _layer_note(openai, "OpenAI", has_fallback=True)
            ),
            "depends_on": ["OPENAI_API_KEY"],
        },
        {
            "id": "editorial",
            "order": 6,
            "label": "Human Editorial Decision",
            "status": "ready",
            "detail": "No API key. The journalist records the outcome in the dashboard.",
            "depends_on": [],
        },
        {
            "id": "documentation",
            "order": 7,
            "label": "Output and Documentation",
            "status": _layer_status(preferred=anthropic, fallback=True),
            "detail": (
                f"Engine: {settings.documentation_model}. "
                + _layer_note(anthropic, "Anthropic", has_fallback=True)
            ),
            "depends_on": ["ANTHROPIC_API_KEY"],
        },
    ]


def _layer_status(*, preferred: str, fallback: bool) -> LayerStatus:
    if preferred == "working":
        return "ready"
    if preferred == "configured":
        return "degraded"
    if fallback:
        return "degraded"
    if preferred == "error":
        return "unavailable"
    return "unavailable"


def _verification_layer(news: str, anthropic: str, factcheck: str) -> LayerStatus:
    if news == "working" and anthropic == "working":
        return "ready"
    if news in {"working", "configured"} or factcheck in {"working", "configured"}:
        return "degraded"
    if news == "error":
        return "unavailable"
    return "unavailable"


def _evidence_layer(hf: str, gemini: str) -> LayerStatus:
    if hf == "working" and gemini == "working":
        return "ready"
    if gemini == "working" or hf in {"working", "configured", "missing"}:
        # NLI always has lexical fallback, Gemini optional
        if gemini == "working":
            return "ready" if hf == "working" else "degraded"
        if gemini == "configured":
            return "degraded"
        return "degraded"
    if gemini == "error" and hf == "error":
        return "unavailable"
    return "degraded"


def _layer_note(status: str, name: str, *, has_fallback: bool) -> str:
    if status == "working":
        return f"{name} is working."
    if status == "configured":
        return f"{name} key is set but not live-tested (or probe skipped)."
    if status == "error":
        return f"{name} key was rejected."
    if has_fallback:
        return f"{name} is missing; fallback is active."
    return f"{name} is missing."
