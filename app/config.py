"""Environment access, per ARCHITECTURE.md §3: importable by every layer,
may import nothing internal itself."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Structured sources (data_catalog.yaml: yfinance_quotes, finnhub_quotes)
    finnhub_api_key: str | None = None

    # Unstructured sources (data_catalog.yaml: sec_edgar_filings, finnhub_news, yfinance_news, elfinanciero_news)
    edgar_user_agent: str | None = None

    # Economic data (data_catalog.yaml: banxico_sie, fred_economic_data — ADR-006)
    banxico_sie_token: str | None = None
    fred_api_key: str | None = None

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
    hybrid_search_enabled: bool = True
    rerank_enabled: bool = False
    temporal_half_life_days_news: int = 14

    # Quality gate (s11-03/s11-04)
    semantic_judge_enabled: bool = False

    # Augmentation (Phase 11, articles/s09-04's 15% output + 5% overhead
    # heuristic on gpt-4o-mini's 128k window would allow ~102k; this
    # project's actual retrieval breadth (vector_top_k=8 per branch) never
    # approaches that, so a conservative, explicit default is used instead
    # of the theoretical ceiling)
    analysis_context_token_budget: int = 12_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
