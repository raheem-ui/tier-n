"""Loads the synthetic Northwind Devices dataset."""
import json
from functools import lru_cache

from .config import DATA_DIR


@lru_cache
def load_company() -> dict:
    return json.loads((DATA_DIR / "suppliers.json").read_text(encoding="utf-8"))


def suppliers_by_id() -> dict[str, dict]:
    return {s["id"]: s for s in load_company()["suppliers"]}


def products() -> dict[str, dict]:
    return load_company()["company"]["products"]


def analyst_name() -> str:
    return load_company()["company"]["analyst"]


@lru_cache
def load_history() -> list[dict]:
    return json.loads((DATA_DIR / "history.json").read_text(encoding="utf-8"))


@lru_cache
def load_events() -> list[dict]:
    return json.loads((DATA_DIR / "events.json").read_text(encoding="utf-8"))
