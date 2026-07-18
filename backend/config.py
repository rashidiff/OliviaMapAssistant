"""Application configuration loaded from environment variables.

Uses pydantic-settings to provide validated, type-safe configuration
with automatic .env file loading.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Resolve the project root (two levels up from this file: backend/config.py → project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load environment variables into os.environ for other libraries (like LangChain/OpenAI) to read
load_dotenv(str(_PROJECT_ROOT / ".env"))


class Settings(BaseSettings):
    """Central configuration for the restaurant discovery system.

    All values can be overridden via environment variables or a ``.env``
    file located at the project root.
    """

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── API keys ──────────────────────────────────────────────────────
    GOOGLE_MAPS_API_KEY: str
    OPENAI_API_KEY: str

    # ── Search defaults ───────────────────────────────────────────────
    DEFAULT_SEARCH_RADIUS: int = 1500  # metres
    DEFAULT_TRAVEL_MODES: list[str] = ["walking", "transit"]
    MAX_RESULTS: int = 3

    # ── Scraping ──────────────────────────────────────────────────────
    REVIEW_SCRAPE_TIMEOUT: int = 30  # seconds

    # ── LLM ───────────────────────────────────────────────────────────
    LLM_MODEL: str = "gpt-4o-mini"


settings = Settings()  # singleton – import this everywhere
