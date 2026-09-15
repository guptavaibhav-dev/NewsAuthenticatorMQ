from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent

DEV_CONTACT_PLACEHOLDER = "https://localhost/newsauth-dev"
INGEST_ACCEPT = "text/html,application/xhtml+xml,application/pdf;q=0.8,*/*;q=0.5"

# Wire agencies whose credit on a page means it is a syndicated copy rather
# than independent reporting. Matched on word boundaries against bylines and
# snippets, longest name first so "Associated Press" wins over "AP".
# Presence of a credit says the text came down a wire; it says nothing about
# whether the reporting is accurate.
WIRE_SERVICES: tuple[str, ...] = (
    "Agence France-Presse",
    "Associated Press",
    "PA Media",
    "Bloomberg",
    "Reuters",
    "AFP",
    "ANI",
    "PTI",
    "AP",
)


def build_user_agent(
    contact_url: str = "",
    environment: str = "development",
    override: str = "",
) -> str:
    """Identify the bot to publishers.

    Default: ``NewsAuthBot/1.0 (+<CONTACT_URL>)``. CONTACT_URL is required in
    production so operators can be reached; a placeholder is allowed in
    development. This is crawler courtesy, not a trust or authenticity claim.
    """
    if (override or "").strip():
        return override.strip()
    url = (contact_url or "").strip()
    env = (environment or "development").lower()
    if not url:
        if env in {"production", "prod"}:
            raise RuntimeError(
                "CONTACT_URL must be set in production so publishers can reach "
                "the operator (User-Agent NewsAuthBot/1.0 (+<CONTACT_URL>))."
            )
        url = DEV_CONTACT_PLACEHOLDER
    return f"NewsAuthBot/1.0 (+{url})"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_BACKEND_DIR / ".env", _BACKEND_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    google_api_key: str = ""
    newsapi_key: str = ""
    guardian_api_key: str = ""
    gnews_api_key: str = ""
    newsdata_api_key: str = ""
    factcheck_api_key: str = ""
    hf_token: str = ""

    preprocess_model: str = "gpt-4.1"
    query_planner_model: str = "claude-sonnet-4-6"
    evidence_llm_model: str = "gemini-3.6-flash"
    uncertainty_model: str = "gpt-4o-mini"
    documentation_model: str = "claude-sonnet-4-6"
    nli_model: str = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"
    nli_fallback_model: str = "facebook/bart-large-mnli"
    embedding_model: str = "sentence-transformers/all-mpnet-base-v2"
    ner_model: str = "dslim/bert-base-NER"

    http_timeout_s: float = 25.0
    ingest_connect_timeout_s: float = 5.0
    ingest_read_timeout_s: float = 20.0
    llm_timeout_s: float = 90.0
    hf_timeout_s: float = 60.0
    max_evidence_items: int = 12
    # 2 = extract claims twice and cross-check by span; 1 = single pass.
    claim_passes: int = 2
    # How many Layer 2 claims Layer 3 plans retrieval queries for.
    retrieval_top_k_claims: int = 5
    # Let an LLM reword planned queries. Off by default: the deterministic
    # planner is reproducible, and a rewrite is only ever accepted whole.
    planner_use_llm: bool = False

    # --- Adapter archive reach, in days. None means apply no age gate. ---
    # An over-tight bound here is worse than a loose one: too small and we
    # report out_of_range for articles we could actually have retrieved,
    # turning our own bad constant into an apparent gap in the source.
    #
    # NewsAPI free Developer plan: "Search articles up to a month old",
    # https://newsapi.org/pricing (checked 2026-09-15). The same page notes a
    # 24-hour publication delay. 30 rather than 29 for the reason above.
    newsapi_max_age_days: int = 30
    # Not verified against either vendor's current free tier, so deliberately
    # left ungated: we would rather attempt the call and record a real empty
    # result than pre-emptively claim the source cannot reach the article.
    # Operators who know their plan should set these.
    gnews_max_age_days: int | None = None
    newsdata_max_age_days: int | None = None
    # GDELT DOC 2.0 needs no key. Its index starts in 2017, which is deeper
    # than any article this tool is likely to see, so no age gate is applied.
    gdelt_max_records: int = 25
    nli_threshold: float = 0.6
    near_duplicate_threshold: float = 0.88
    log_level: str = "INFO"
    contact_url: str = ""
    environment: str = "development"
    user_agent: str = ""

    @property
    def gemini_key(self) -> str:
        return self.gemini_api_key or self.google_api_key

    @property
    def factcheck_key(self) -> str:
        return self.factcheck_api_key or self.google_api_key or self.gemini_api_key

    @property
    def app_user_agent(self) -> str:
        return build_user_agent(self.contact_url, self.environment, self.user_agent)

    @model_validator(mode="after")
    def _require_contact_url_in_production(self) -> Settings:
        _ = self.app_user_agent
        return self

    @model_validator(mode="after")
    def _clamp_claim_passes(self) -> Settings:
        if self.claim_passes not in {1, 2}:
            raise ValueError("CLAIM_PASSES must be 1 or 2")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Wikipedia and the shared HTTP client import this name. Resolved from Settings
# (env / .env) at import so Layer 3 files do not need a call-site change.
APP_USER_AGENT = get_settings().app_user_agent
