"""Runtime configuration, read from environment / .env."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    hindsight_base_url: str = os.getenv("HINDSIGHT_BASE_URL", "http://localhost:8888")
    hindsight_api_key: str | None = os.getenv("HINDSIGHT_API_KEY") or None
    bank_id: str = os.getenv("TIERN_BANK_ID", "northwind-supply-risk")
    groq_api_key: str | None = os.getenv("GROQ_API_KEY") or None
    groq_model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


settings = Settings()
