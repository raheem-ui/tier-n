"""Everything Tier-N remembers lives in one Hindsight memory bank.

What goes in (retain):
  - past incidents, decisions and outcomes, audits  (seeded from data/history.json)
  - every live event Tier-N analyses
  - every accept/reject the analyst gives a recommendation, with her reason
  - free-text corrections ("Brightline's CAPA closed last week")

What comes out:
  - recall()  -> cited evidence for a brief (semantic + keyword + graph + temporal)
  - reflect() -> free-form questions in the "Ask memory" tab
"""
import asyncio
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

from .config import settings
from .data import analyst_name, load_history, suppliers_by_id

MISSION = (
    "I am Tier-N, a senior supply-chain risk analyst for Northwind Devices. "
    "I remember every supplier incident, what mitigation worked, which alternates are safe, "
    "and how the analyst I work with likes her briefs."
)

DIRECTIVES = [
    ("quantify", "When assessing a specific disruption event, lead with revenue at risk in USD. "
                 "For general questions, answer directly without a revenue headline."),
    ("evidence", "Only state supplier history that is supported by a stored memory."),
    ("latest-wins", "When two memories about a supplier conflict, trust the most recent one."),
]


@dataclass
class Fact:
    ref: str  # short citation label, e.g. "M3"
    id: str
    text: str
    type: str
    date: str | None


def _date(ts) -> datetime:
    return datetime.fromisoformat(ts) if isinstance(ts, str) else ts


def _similar(a: set[str], b: set[str], threshold: float = 0.7) -> bool:
    """Word-overlap (Jaccard) test for near-duplicate facts."""
    return bool(a and b) and len(a & b) / len(a | b) >= threshold


class _LoopBound:
    """Runs the client's async methods on one long-lived event loop.

    The SDK's sync wrappers use the calling thread's event loop, which breaks
    under Streamlit (each rerun can be a different thread and the HTTP session
    stays bound to the first loop). `client.recall(...)` here calls
    `client.arecall(...)` on a dedicated background loop instead.
    """

    def __init__(self, client):
        self._client = client
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True, name="hindsight-loop").start()

    def __getattr__(self, name):
        method = getattr(self._client, f"a{name}")

        def call(*args, **kwargs):
            return asyncio.run_coroutine_threadsafe(method(*args, **kwargs), self._loop).result()

        return call


class Memory:
    def __init__(self, client=None, bank_id: str | None = None):
        if client is None:
            from hindsight_client import Hindsight

            client = _LoopBound(
                Hindsight(base_url=settings.hindsight_base_url, api_key=settings.hindsight_api_key, timeout=120)
            )
        self.client = client
        self.bank_id = bank_id or settings.bank_id

    # ---- setup -------------------------------------------------------------
    def create_bank(self) -> None:
        self.client.create_bank(
            bank_id=self.bank_id,
            name="Tier-N supply risk analyst",
            mission=MISSION,
            disposition_skepticism=4,
            disposition_literalism=3,
            disposition_empathy=2,
            retain_mission=(
                "Extract supplier names, IDs, ports, dates, costs, durations, outcomes, audit status, "
                "and the analyst's preferences and bans."
            ),
        )
        for name, content in DIRECTIVES:
            try:
                self.client.create_directive(bank_id=self.bank_id, name=name, content=content)
            except Exception:
                pass  # directive already exists

    def seed_history(self) -> int:
        catalog = suppliers_by_id()
        items = []
        for h in load_history():
            items.append(
                {
                    "content": h["content"],
                    "context": f"Northwind supply-chain {h['kind']} record",
                    "timestamp": _date(h["date"]),
                    "document_id": h["id"],
                    "metadata": {"kind": h["kind"], "suppliers": ",".join(h["suppliers"])},
                    "tags": [h["kind"]] + [f"supplier:{s}" for s in h["suppliers"]],
                    "entities": [{"text": catalog[s]["name"]} for s in h["suppliers"] if s in catalog],
                }
            )
        self.client.retain_batch(bank_id=self.bank_id, items=items)
        return len(items)

    def reset(self) -> int:
        try:
            self.client.delete_bank(bank_id=self.bank_id)
        except Exception:
            pass  # bank didn't exist
        self.create_bank()
        return self.seed_history()

    # ---- read ----------------------------------------------------------------
    def recall_for_event(self, event: dict, max_facts: int = 24) -> list[Fact]:
        catalog = suppliers_by_id()
        affected = [catalog[s] for s in event["affected_suppliers"] if s in catalog]
        alternates = list({a: catalog[a] for s in affected for a in s["qualified_alternates"] if a in catalog}.values())
        ports = ", ".join(sorted({s["port"] for s in affected}))
        # One query per purpose (and per alternate): a single broad query lets new
        # memories about one supplier crowd out the audit status of another.
        queries: list[tuple[str, int]] = [
            (
                f"{event['title']}. Past incidents, real delays, mitigations and their cost involving "
                f"{', '.join(s['name'] for s in affected)} or the port of {ports}. Logistics lessons and timing.",
                7,
            )
        ]
        queries += [
            (
                f"Current status of {s['name']} ({s['id']}): audits, corrective actions, bans, labor disputes, "
                "capacity, consignment stock, and the latest corrections.",
                4,
            )
            for s in alternates
        ]
        queries.append(
            (f"{analyst_name()}'s preferences, bans and lessons learned for supplier risk briefs and sourcing decisions.", 6)
        )
        with ThreadPoolExecutor(max_workers=len(queries)) as pool:
            responses = list(
                pool.map(
                    lambda q: self.client.recall(
                        bank_id=self.bank_id, query=q[0], budget="mid", max_tokens=2500, query_timestamp=event["date"]
                    ),
                    queries,
                )
            )
        facts: list[Fact] = []
        seen_ids: set[str] = set()
        seen_words: list[set[str]] = []
        for (_, per_query), resp in zip(queries, responses):
            if len(facts) >= max_facts:
                break
            taken = 0
            for r in resp.results or []:
                text = r.text.split(" | ")[0].strip()  # drop "| When: ... | Involving: ..." suffix
                words = set(re.findall(r"[a-z0-9]+", text.lower()))
                if r.id in seen_ids or any(_similar(words, w) for w in seen_words):
                    continue  # Hindsight can extract near-identical facts from one source
                seen_ids.add(r.id)
                seen_words.append(words)
                when = r.occurred_start or r.mentioned_at
                facts.append(
                    Fact(
                        ref=f"M{len(facts) + 1}",
                        id=r.id,
                        text=text,
                        type=r.type or "world",
                        date=str(when)[:10] if when else None,
                    )
                )
                taken += 1
                if taken >= per_query or len(facts) >= max_facts:
                    break
        return facts

    def ask(self, question: str, max_sources: int = 12) -> tuple[str, list[str]]:
        resp = self.client.reflect(bank_id=self.bank_id, query=question, budget="mid", include_facts=True)
        sources: list[str] = []
        seen_words: list[set[str]] = []
        based_on = getattr(resp, "based_on", None)
        for f in getattr(based_on, "memories", None) or []:
            text = str(getattr(f, "text", f)).split(" | ")[0].strip()
            words = set(re.findall(r"[a-z0-9]+", text.lower()))
            if any(_similar(words, w) for w in seen_words):
                continue
            seen_words.append(words)
            sources.append(text)
            if len(sources) >= max_sources:
                break
        return resp.text, sources

    def memory_count(self) -> int | None:
        try:
            return self.client.list_memories(bank_id=self.bank_id, limit=1).total
        except Exception:
            return None

    # ---- write ---------------------------------------------------------------
    def retain_event(self, event: dict, headline: str) -> None:
        self.client.retain(
            bank_id=self.bank_id,
            content=f"Disruption event on {event['date']}: {event['title']}. {event['description']} "
            f"Tier-N's assessment: {headline}",
            context="live disruption event analysed by Tier-N",
            timestamp=_date(event["date"]),
            document_id=f"event-{event['id']}",
            tags=["event"] + [f"supplier:{s}" for s in event["affected_suppliers"]],
            retain_async=True,
        )

    def retain_feedback(self, event: dict, action: str, accepted: bool, note: str = "") -> None:
        verdict = "accepted" if accepted else "rejected"
        content = f"For '{event['title']}' ({event['date']}), Tier-N recommended: {action}. {analyst_name()} {verdict} it."
        if note:
            content += f" Her reason: {note}"
        self.client.retain(
            bank_id=self.bank_id,
            content=content,
            context="analyst feedback on a Tier-N recommendation",
            timestamp=_date(event["date"]),
            tags=["feedback", verdict] + [f"supplier:{s}" for s in event["affected_suppliers"]],
            retain_async=True,  # keep the click instant; extraction finishes server-side
        )

    def retain_correction(self, text: str, when: str) -> None:
        self.client.retain(
            bank_id=self.bank_id,
            content=f"Correction from {analyst_name()} on {when}: {text}",
            context="analyst correction - this supersedes older memories on the same topic",
            timestamp=_date(when),
            tags=["correction"],
        )
