from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent

APP_USER_AGENT = (
    "NewsAuthBot/1.0 (https://github.com/guptavaibhav-dev/"
    "A-Framework-for-Authenticating-News-Content; thesis prototype)"
)


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
    query_planner_model: str = "claude-sonnet-4-20250514"
    evidence_llm_model: str = "gemini-2.5-pro"
    uncertainty_model: str = "o4-mini"
    documentation_model: str = "claude-sonnet-4-20250514"
    nli_model: str = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"
    embedding_model: str = "sentence-transformers/all-mpnet-base-v2"
    ner_model: str = "dslim/bert-base-NER"

    http_timeout_s: float = 25.0
    max_evidence_items: int = 12
    nli_threshold: float = 0.6
    near_duplicate_threshold: float = 0.88

    @property
    def gemini_key(self) -> str:
        return self.gemini_api_key or self.google_api_key

    @property
    def factcheck_key(self) -> str:
        return self.factcheck_api_key or self.google_api_key or self.gemini_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
