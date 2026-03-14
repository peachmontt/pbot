from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ANALYZER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    wallets: list[str] = []
    lookback_days: int = 30
    db_path: Path = Path("data/analyzer.db")

    max_concurrent_requests: int = 5
    request_delay_ms: int = 200

    data_api_base: str = "https://data-api.polymarket.com"
    clob_api_base: str = "https://clob.polymarket.com"

    @field_validator("wallets", mode="before")
    @classmethod
    def parse_wallets(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [w.strip() for w in v.split(",") if w.strip()]
        return v


settings = Settings()
