from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import Settings
from app.logutil import get_logger, http_error_detail, short_error

log = get_logger("llm")

MODEL_FALLBACKS = {
    "openai": ["gpt-4.1", "gpt-4o", "gpt-4o-mini"],
    "anthropic": [
        "claude-sonnet-4-6",
        "claude-sonnet-4-5",
        "claude-sonnet-4-5-20250929",
        "claude-3-5-sonnet-latest",
    ],
    "gemini": [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-flash-latest",
        "gemini-2.5-pro",
    ],
}


def _models_to_try(provider: str, requested: str) -> list[str]:
    chain = [requested]
    for alt in MODEL_FALLBACKS.get(provider, []):
        if alt not in chain:
            chain.append(alt)
    return chain


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> dict[str, Any]:
    if not text:
        raise ValueError("empty model response")
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK.search(stripped)
    if not match:
        raise ValueError("no JSON object in model response")
    value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("JSON was not an object")
    return value


class LLMRouter:
    """Pinned-model chat router. Each layer must pass its own model id."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    def openai_ready(self) -> bool:
        return bool(self.settings.openai_api_key)

    def anthropic_ready(self) -> bool:
        return bool(self.settings.anthropic_api_key)

    def gemini_ready(self) -> bool:
        return bool(self.settings.gemini_key)

    async def chat_json(
        self,
        *,
        provider: str,
        model: str,
        system: str,
        user: str,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        raw = await self.chat(
            provider=provider,
            model=model,
            system=system,
            user=user,
            temperature=temperature,
            json_mode=True,
        )
        return extract_json(raw)

    async def chat(
        self,
        *,
        provider: str,
        model: str,
        system: str,
        user: str,
        temperature: float = 0.1,
        json_mode: bool = False,
    ) -> str:
        last_error: Exception | None = None
        for candidate in _models_to_try(provider, model):
            log.info("llm request provider=%s model=%s json=%s", provider, candidate, json_mode)
            try:
                if provider == "openai":
                    text = await self._openai(candidate, system, user, temperature, json_mode)
                elif provider == "anthropic":
                    text = await self._anthropic(candidate, system, user, temperature)
                elif provider == "gemini":
                    text = await self._gemini(candidate, system, user, temperature, json_mode)
                else:
                    raise ValueError(f"unknown provider {provider}")
            except httpx.HTTPStatusError as exc:
                detail = http_error_detail(exc.response)
                log.error("llm error provider=%s model=%s %s", provider, candidate, detail)
                last_error = RuntimeError(detail)
                if exc.response.status_code in {404, 400, 410} and candidate != _models_to_try(provider, model)[-1]:
                    log.warning("llm trying next model after %s failed", candidate)
                    continue
                raise RuntimeError(detail) from exc
            except Exception as exc:
                log.error(
                    "llm error provider=%s model=%s %s",
                    provider,
                    candidate,
                    short_error(exc),
                )
                last_error = exc
                message = str(exc)
                if "HTTP 404" in message or "HTTP 410" in message or "no longer available" in message:
                    log.warning("llm trying next model after %s failed", candidate)
                    continue
                raise
            log.info("llm ok provider=%s model=%s chars=%s", provider, candidate, len(text))
            return text
        if last_error:
            raise last_error
        raise RuntimeError(f"no model available for {provider}")

    async def _openai(
        self,
        model: str,
        system: str,
        user: str,
        temperature: float,
        json_mode: bool,
    ) -> str:
        if not self.settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        # o-series models reject temperature / some response formats
        if model.startswith("o"):
            body.pop("temperature", None)
        response = await self.client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
            json=body,
        )
        if response.status_code >= 400 and json_mode:
            body.pop("response_format", None)
            response = await self.client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                json=body,
            )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"] or ""

    async def _anthropic(
        self,
        model: str,
        system: str,
        user: str,
        temperature: float,
    ) -> str:
        if not self.settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        response = await self.client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 4096,
                "temperature": temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        response.raise_for_status()
        data = response.json()
        parts = [
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        ]
        return "".join(parts)

    async def _gemini(
        self,
        model: str,
        system: str,
        user: str,
        temperature: float,
        json_mode: bool,
    ) -> str:
        key = self.settings.gemini_key
        if not key:
            raise RuntimeError("GEMINI_API_KEY / GOOGLE_API_KEY is not set")
        generation: dict[str, Any] = {"temperature": temperature}
        if json_mode:
            generation["responseMimeType"] = "application/json"
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        response = await self.client.post(
            url,
            params={"key": key},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": generation,
            },
        )
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError("Gemini returned no candidates")
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(part.get("text", "") for part in parts)
