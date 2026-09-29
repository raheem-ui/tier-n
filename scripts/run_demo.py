"""Terminal smoke test: analyse one event with and without memory.

    python scripts/run_demo.py E1
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tier_n.agent import TierN, brief_to_markdown  # noqa: E402
from tier_n.data import load_events  # noqa: E402
from tier_n.llm import GroqJSON  # noqa: E402
from tier_n.memory import Memory  # noqa: E402

if __name__ == "__main__":
    event_id = sys.argv[1] if len(sys.argv) > 1 else "E1"
    event = next(e for e in load_events() if e["id"] == event_id)
    agent = TierN(memory=Memory(), llm=GroqJSON())
    for use_memory in (False, True):
        b = agent.analyze(event, use_memory=use_memory, remember=False)
        print("=" * 30, "WITH MEMORY" if use_memory else "NO MEMORY", "=" * 30)
        print(brief_to_markdown(b))
        if b.degraded:
            print("DEGRADED:", b.degraded)
        for f in b.facts:
            print(f"  [{f.ref}] {f.date} {f.text[:110]}")
