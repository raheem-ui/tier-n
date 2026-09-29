"""Create (or rebuild) the Tier-N memory bank and load Northwind's history.

    python scripts/seed.py            # rebuild from scratch (safe to re-run before a demo)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tier_n import ledger  # noqa: E402
from tier_n.config import settings  # noqa: E402
from tier_n.memory import Memory  # noqa: E402

if __name__ == "__main__":
    print(f"Hindsight: {settings.hindsight_base_url}  bank: {settings.bank_id}")
    n = Memory().reset()
    ledger.clear()
    print(f"Seeded {n} history records. Ready for demo.")
