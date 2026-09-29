"""Local log of analyst verdicts, used to chart whether Tier-N is getting better.

The feedback itself is retained in Hindsight (that's what changes behaviour);
this file only powers the acceptance-rate chart.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import DATA_DIR

LEDGER = DATA_DIR / "feedback_log.jsonl"


def record(event_id: str, action: str, accepted: bool, use_memory: bool, path: Path = LEDGER) -> None:
    row = {
        "at": datetime.now(timezone.utc).isoformat(),
        "event_id": event_id,
        "action": action,
        "accepted": accepted,
        "use_memory": use_memory,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def rows(path: Path = LEDGER) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def acceptance_by_event(path: Path = LEDGER) -> list[dict]:
    """[{event_id, mode, accepted, total, rate}] in first-seen order."""
    stats: dict[tuple[str, str], list[int]] = {}
    for r in rows(path):
        key = (r["event_id"], "with memory" if r["use_memory"] else "no memory")
        s = stats.setdefault(key, [0, 0])
        s[0] += int(bool(r["accepted"]))
        s[1] += 1
    return [
        {"event_id": e, "mode": m, "accepted": a, "total": t, "rate": a / t}
        for (e, m), (a, t) in stats.items()
    ]


def clear(path: Path = LEDGER) -> None:
    path.unlink(missing_ok=True)
