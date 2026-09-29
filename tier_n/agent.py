"""Tier-N: turns a disruption event (+ memories) into a cited, quantified risk brief."""
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache

from .data import analyst_name, products, suppliers_by_id
from .exposure import Exposure, compute_exposure
from .llm import GroqJSON, LLMError
from .memory import Fact, Memory

SYSTEM = """You are Tier-N, a senior supply-chain risk analyst for Northwind Devices (networking hardware).
You write disruption briefs for {analyst}. Use ONLY the event, the exposure table and the numbered memories given.
Rules:
- Cite memories by their label (e.g. "M3") in the "evidence" lists. Never cite a label that was not provided.
- If memories show that past disruptions like this one ran longer than announced, set adjusted_disruption_days accordingly and explain why, citing the memory. Otherwise use the announced length.
- Never recommend a supplier or channel that a memory says is banned, failed an audit, or is otherwise unsafe - put it in "avoid" instead.
- When memories conflict, the most recent one wins.
- If there are no memories, rely on general supply-chain practice and say so; do not invent history.
- Do NOT write any revenue-at-risk dollar figure in headline or summary: the system recomputes it from adjusted_disruption_days and displays it separately. Describe the gap in days instead.
- Base est_cost_usd on remembered costs when a memory has one (scale proportionally if volume differs); otherwise null.
- Put citations only in "evidence" arrays, not inside rationale text.
Return ONLY a JSON object with keys:
headline (string, <= 15 words),
adjusted_disruption_days (integer),
adjustment_reason (string),
summary (string, <= 70 words),
recommendations (array of {{action, time_to_effect (short text such as "same day", "48 hours", "1 week"), est_cost_usd (integer or null), rationale, evidence (array of labels)}}; ranked fastest time-to-effect first; max 4),
avoid (array of {{what, why, evidence}}; may be empty),
open_questions (array of strings; max 3)."""

REQUIRED = ("headline", "adjusted_disruption_days", "summary", "recommendations")


@dataclass
class Brief:
    event_id: str
    use_memory: bool
    headline: str
    summary: str
    announced_days: int
    adjusted_days: int
    adjustment_reason: str
    exposure: Exposure
    recommendations: list[dict]
    avoid: list[dict]
    open_questions: list[str]
    facts: list[Fact] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)  # actions removed for contradicting "avoid"
    degraded: str | None = None  # set when we fell back to a non-LLM brief
    latency_s: float = 0.0

    def fact(self, ref: str) -> Fact | None:
        return next((f for f in self.facts if f.ref == ref), None)


def _exposure_table(exp: Exposure) -> str:
    """Buffers only - no dollar or gap figures, so the model can't anchor on the
    announced-length number before memory has adjusted the disruption length."""
    prods = products()
    return "\n".join(
        f"- {s.supplier_id} {s.supplier_name}: supplies {', '.join(s.parts)} for "
        f"{', '.join(prods[p]['name'] for p in s.products)}; inventory buffer {s.inventory_days} days"
        for s in exp.suppliers
    )


def _alternates_table(event: dict) -> str:
    catalog = suppliers_by_id()
    lines = []
    for sid in event["affected_suppliers"]:
        s = catalog.get(sid)
        if not s:
            continue
        alts = [f"{a} {catalog[a]['name']} ({catalog[a]['country']})" for a in s["qualified_alternates"] if a in catalog]
        lines.append(f"- {s['name']}: qualified alternates: {', '.join(alts) or 'none (single source)'}")
    return "\n".join(lines)


def _clean_evidence(items: list[dict], valid: set[str]) -> list[dict]:
    """Drop hallucinated citations so every chip in the UI resolves to a real memory."""
    cleaned = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        ev = it.get("evidence") or []
        it["evidence"] = [e for e in ev if isinstance(e, str) and e in valid]
        cleaned.append(it)
    return cleaned


_GENERIC = {"electronics", "precision", "advanced", "technologies", "group", "works", "power", "modules", "circuit",
             "board", "assembly", "capacitors", "substrates", "substrate", "semiconductor", "polymer", "housings",
             "molding"}


@lru_cache
def _supplier_keywords() -> dict[str, set[str]]:
    """Words that identify one supplier on their own, e.g. "brightline" -> S07, "penang" -> S08.

    Place names shared by several suppliers are excluded, so "Kaohsiung airport"
    doesn't match Kaohsiung Advanced Substrates.
    """
    catalog = suppliers_by_id()
    place_owners: dict[str, set[str]] = {}
    for sid, s in catalog.items():
        for f in ("city", "country", "port"):
            for w in re.findall(r"[a-zé]+", s[f].lower()):
                place_owners.setdefault(w, set()).add(sid)
    shared_places = {w for w, owners in place_owners.items() if len(owners) > 1}
    words = {sid: set(re.findall(r"[a-zé]+", s["name"].lower())) - shared_places - _GENERIC for sid, s in catalog.items()}
    counts: dict[str, int] = {}
    for ws in words.values():
        for w in ws:
            counts[w] = counts.get(w, 0) + 1
    return {sid: {w for w in ws if counts[w] == 1} for sid, ws in words.items()}


def _mentioned_suppliers(text: str) -> set[str]:
    text = text.lower()
    tokens = set(re.findall(r"[a-zé0-9]+", text))
    return {
        sid
        for sid, s in suppliers_by_id().items()
        if s["name"].lower() in text or sid.lower() in tokens or _supplier_keywords()[sid] & tokens
    }


def _drop_conflicts(recs: list[dict], avoid: list[dict]) -> tuple[list[dict], list[str]]:
    """A supplier the brief says to avoid can never also appear in an action."""
    banned = set().union(*(_mentioned_suppliers(str(a.get("what", ""))) for a in avoid)) if avoid else set()
    kept, dropped = [], []
    for r in recs:
        if _mentioned_suppliers(str(r.get("action", ""))) & banned:
            dropped.append(str(r.get("action", "")))
        else:
            kept.append(r)
    return kept, dropped


def _clamp_days(value, announced: int) -> int:
    """Allow memory to stretch the disruption, but not to absurd values or below zero."""
    try:
        days = int(value)
    except (TypeError, ValueError):
        return announced
    return max(0, min(days, announced * 4 + 10))


def _fallback(event: dict, use_memory: bool, facts: list[Fact], exposure: Exposure, reason: str) -> Brief:
    return Brief(
        event_id=event["id"],
        use_memory=use_memory,
        headline=f"{event['title']} - ${exposure.total_usd:,} revenue at risk",
        summary="The language model was unavailable, so this is the deterministic exposure view only. "
        "Relevant memories are listed below for manual review.",
        announced_days=event["expected_disruption_days"],
        adjusted_days=exposure.disruption_days,
        adjustment_reason="not assessed",
        exposure=exposure,
        recommendations=[],
        avoid=[],
        open_questions=[],
        facts=facts,
        degraded=reason,
    )


class TierN:
    def __init__(self, memory: Memory | None = None, llm: GroqJSON | None = None):
        self.memory = memory
        self.llm = llm

    def analyze(self, event: dict, use_memory: bool = True, remember: bool = True) -> Brief:
        t0 = time.time()
        announced = int(event["expected_disruption_days"])
        facts: list[Fact] = []
        if use_memory and self.memory is not None:
            facts = self.memory.recall_for_event(event)

        naive = compute_exposure(event["affected_suppliers"], announced)
        memories = "\n".join(f"[{f.ref}] ({f.date or 'undated'}) {f.text}" for f in facts) or "(no memories available)"
        user = (
            f"EVENT ({event['date']}): {event['title']}\n{event['description']}\n"
            f"Announced disruption: {announced} days\n\n"
            f"AFFECTED SUPPLIERS:\n{_exposure_table(naive)}\n\n"
            f"ALTERNATES ON FILE:\n{_alternates_table(event)}\n\n"
            f"MEMORIES:\n{memories}"
        )

        try:
            if self.llm is None:
                raise LLMError("no LLM configured")
            out = self.llm.complete(SYSTEM.format(analyst=analyst_name()), user, required_keys=REQUIRED)
        except LLMError as e:
            brief = _fallback(event, use_memory, facts, naive, str(e))
            brief.latency_s = time.time() - t0
            return brief

        valid = {f.ref for f in facts}
        avoid = _clean_evidence(out.get("avoid"), valid)
        recs, dropped = _drop_conflicts(_clean_evidence(out.get("recommendations"), valid), avoid)
        adjusted = _clamp_days(out.get("adjusted_disruption_days"), announced)
        exposure = compute_exposure(event["affected_suppliers"], adjusted) if adjusted != announced else naive
        brief = Brief(
            event_id=event["id"],
            use_memory=use_memory,
            headline=str(out.get("headline", "")).strip(),
            summary=str(out.get("summary", "")).strip(),
            announced_days=announced,
            adjusted_days=adjusted,
            adjustment_reason=str(out.get("adjustment_reason", "")).strip(),
            exposure=exposure,
            recommendations=recs[:4],
            avoid=avoid,
            blocked=dropped,
            open_questions=[str(q) for q in (out.get("open_questions") or [])][:3],
            facts=facts,
            latency_s=time.time() - t0,
        )
        if remember and use_memory and self.memory is not None:
            try:
                self.memory.retain_event(event, brief.headline)
            except Exception:
                pass  # never lose a brief because a background write failed
        return brief


def brief_to_markdown(b: Brief) -> str:
    """Plain-text export for pasting into email/Slack."""
    lines = [f"# {b.headline}", "", f"**Revenue at risk:** ${b.exposure.total_usd:,} "
             f"(disruption {b.adjusted_days}d, announced {b.announced_days}d)", "", b.summary, "", "## Actions"]
    for i, r in enumerate(b.recommendations, 1):
        cost = f" - est. ${r['est_cost_usd']:,}" if isinstance(r.get("est_cost_usd"), int) else ""
        lines.append(f"{i}. **{r.get('action')}** ({r.get('time_to_effect')}){cost}. {r.get('rationale')}")
    if b.avoid:
        lines += ["", "## Avoid"] + [f"- **{a.get('what')}**: {a.get('why')}" for a in b.avoid]
    return "\n".join(lines)
