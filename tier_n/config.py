"""Runtime configuration: Streamlit secrets (cloud), then environment / .env (local)."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

load_dotenv(ROOT / ".env")


def _get(name: str, default: str | None = None) -> str | None:
    """Streamlit Cloud secrets aren't in os.environ until st.secrets is touched, so read them directly."""
    value = None
    try:
        import streamlit as st

        if name in st.secrets:
            value = st.secrets[name]
    except Exception:
        pass  # no secrets.toml locally, or not running under Streamlit
    if value is None:
        value = os.getenv(name)
    if value is None:
        return default
    value = str(value).strip().strip('"').strip("'").strip()  # tolerate pasted quotes/spaces
    return value or default


@dataclass(frozen=True)
class Settings:
    hindsight_base_url: str = _get("HINDSIGHT_BASE_URL", "http://localhost:8888")
    hindsight_api_key: str | None = _get("HINDSIGHT_API_KEY")
    bank_id: str = _get("TIERN_BANK_ID", "northwind-supply-risk")
    groq_api_key: str | None = _get("GROQ_API_KEY")
    groq_model: str = _get("GROQ_MODEL", "openai/gpt-oss-120b")


settings = Settings()
