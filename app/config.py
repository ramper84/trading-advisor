"""Environment access, per ARCHITECTURE.md §3: importable by every layer,
may import nothing internal itself."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Structured sources (data_catalog.yaml: yfinance_quotes, finnhub_quotes)
    finnhub_api_key: str | None = None

    # Unstructured sources (data_catalog.yaml: sec_edgar_filings, finnhub_news, reddit_mentions)
    edgar_user_agent: str | None = None
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = "trading-advisor/0.1"

    # LLM + embeddings
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # Store
    database_url: str = "postgresql+psycopg://trading-advisor:trading-advisor@postgres:5432/trading-advisor"
    redis_url: str = "redis://redis:6379"

    # Freshness — structured live-read path only; unstructured cadence lives in data_catalog.yaml
    freshness_budget_seconds: int = 30

    # Vector retrieval (Axis 3)
    vector_top_k: int = 8
    vector_distance_threshold: float = 0.35


@lru_cache
def get_settings() -> Settings:
    return Settings()
