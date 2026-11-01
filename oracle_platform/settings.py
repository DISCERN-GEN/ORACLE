from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal


def _decimal(name: str, default: str) -> Decimal:
    return Decimal(os.getenv(name, default))


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str = os.getenv("ORACLE_ENV", "development")
    api_token: str = os.getenv("ORACLE_API_TOKEN", "change-this-long-random-token")
    database_url: str = os.getenv("DATABASE_URL", "")
    valkey_url: str = os.getenv("VALKEY_URL", "")
    gamma_url: str = os.getenv("POLYMARKET_GAMMA_URL", "https://gamma-api.polymarket.com")
    clob_url: str = os.getenv("POLYMARKET_CLOB_URL", "https://clob.polymarket.com")
    data_url: str = os.getenv("POLYMARKET_DATA_URL", "https://data-api.polymarket.com")
    geoblock_url: str = os.getenv("POLYMARKET_GEO_URL", "https://polymarket.com/api/geoblock")
    paper_initial_bankroll: Decimal = _decimal("PAPER_INITIAL_BANKROLL", "10000")
    paper_max_order_notional: Decimal = _decimal("PAPER_MAX_ORDER_NOTIONAL", "100")
    paper_max_single_market_exposure: Decimal = _decimal("PAPER_MAX_SINGLE_MARKET_EXPOSURE", "500")
    paper_max_portfolio_exposure: Decimal = _decimal("PAPER_MAX_PORTFOLIO_EXPOSURE", "2500")
    paper_max_daily_loss: Decimal = _decimal("PAPER_MAX_DAILY_LOSS", "200")
    paper_max_kelly_fraction: Decimal = _decimal("PAPER_MAX_KELLY_FRACTION", "0.02")
    market_data_max_age_seconds: int = int(os.getenv("MARKET_DATA_MAX_AGE_SECONDS", "30"))
    paper_session_hours: int = int(os.getenv("PAPER_SESSION_HOURS", "12"))
    enable_live_execution: bool = _bool("ENABLE_LIVE_EXECUTION", False)
    live_legal_review_approved: bool = _bool("LIVE_LEGAL_REVIEW_APPROVED", False)
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "")


settings = Settings()
