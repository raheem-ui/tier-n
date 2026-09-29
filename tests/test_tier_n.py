"""Offline tests: no Hindsight or Groq calls are made."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tier_n import ledger  # noqa: E402
from tier_n.agent import TierN  # noqa: E402
from tier_n.data import load_events  # noqa: E402
from tier_n.exposure import compute_exposure  # noqa: E402
from tier_n.llm import GroqJSON, LLMError, parse_json_object  # noqa: E402
from tier_n.memory import Fact  # noqa: E402

E1 = next(e for e in load_events() if e["id"] == "E1")


# ---- fakes -----------------------------------------------------------------------
class FakeCompletions:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def create(self, **_):
        self.calls += 1
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=out))])


def fake_llm(*outputs) -> GroqJSON:
    completions = FakeCompletions(outputs)
    return GroqJSON(client=SimpleNamespace(chat=SimpleNamespace(completions=completions)), model="fake")


class FakeMemory:
    def __init__(self, facts):
        self.facts = facts
        self.retained = []

    def recall_for_event(self, event):
        return self.facts

    def retain_event(self, event, headline):
        self.retained.append(headline)


FACTS = [
    Fact("M1", "a", "Kaohsiung closures run ~5 days longer than announced due to backlog.", "world", "2024-07-26"),
    Fact("M2", "b", "Brightline failed a quality audit; CAPA open.", "world", "2026-03-10"),
]

GOOD = {
    "headline": "Kaohsiung typhoon puts capacitor supply at risk",
    "adjusted_disruption_days": 10,
    "adjustment_reason": "Backlog adds ~5 days (M1)",
    "summary": "...",
    "recommendations": [
        {"action": "Book air freight today", "time_to_effect": "24h", "est_cost_usd": 180000,
         "rationale": "worked in 2024", "evidence": ["M1", "M9"]},
    ],
    "avoid": [{"what": "Brightline", "why": "open CAPA", "evidence": ["M2"]}],
    "open_questions": [],
}


# ---- exposure --------------------------------------------------------------------
def test_buffer_absorbs_short_disruption():
    # S01 has 6 days of inventory, S02 has 14: a 5-day closure looks harmless.
    assert compute_exposure(["S01", "S02"], 5).total_usd == 0


def test_longer_disruption_creates_gap():
    exp = compute_exposure(["S01", "S02"], 10)
    s01 = next(s for s in exp.suppliers if s.supplier_id == "S01")
    assert s01.gap_days == 4
    # 0.7 share x 4 days x (410k AUR-1 + 265k NIM-2)
    assert exp.total_usd == round(410_000 * 0.7 * 4) + round(265_000 * 0.7 * 4)


def test_product_loss_capped_at_full_stoppage():
    # S01 (0.7) + S07 (0.2) + S08 (0.1) all feed AUR-1; even if all fail the loss is <= 100% per day.
    exp = compute_exposure(["S01", "S07", "S08"], 30)
    assert exp.by_product_usd["AUR-1"] <= 410_000 * 30


def test_unknown_supplier_ignored():
    assert compute_exposure(["NOPE"], 10).total_usd == 0


# ---- llm parsing -------------------------------------------------------------------
def test_parse_json_with_fences_and_chatter():
    assert parse_json_object('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('blah {"a": {"b": 2}} blah') == {"a": {"b": 2}}


def test_parse_json_rejects_garbage():
    with pytest.raises(ValueError):
        parse_json_object("no json here")


def test_llm_retries_on_invalid_then_succeeds():
    llm = fake_llm("not json", json.dumps({"x": 1}))
    assert llm.complete("s", "u", required_keys=("x",)) == {"x": 1}
    assert llm.client.chat.completions.calls == 2


def test_llm_raises_after_attempts(monkeypatch):
    monkeypatch.setattr("tier_n.llm.time.sleep", lambda *_: None)
    llm = fake_llm(RuntimeError("429"), RuntimeError("429"), RuntimeError("429"))
    with pytest.raises(LLMError):
        llm.complete("s", "u")


# ---- agent -----------------------------------------------------------------------
def test_memory_adjusts_exposure_and_drops_fake_citations():
    mem = FakeMemory(FACTS)
    brief = TierN(memory=mem, llm=fake_llm(json.dumps(GOOD))).analyze(E1, use_memory=True)
    assert brief.adjusted_days == 10
    assert brief.exposure.total_usd > 0  # naive 5-day view would be $0
    assert brief.recommendations[0]["evidence"] == ["M1"]  # hallucinated M9 removed
    assert mem.retained == [GOOD["headline"]]


def test_no_memory_mode_does_not_recall_or_retain():
    mem = FakeMemory(FACTS)
    out = dict(GOOD, adjusted_disruption_days=5)
    brief = TierN(memory=mem, llm=fake_llm(json.dumps(out))).analyze(E1, use_memory=False)
    assert brief.facts == [] and mem.retained == []
    assert brief.exposure.total_usd == 0
    assert brief.recommendations[0]["evidence"] == []


def test_absurd_adjustment_is_clamped():
    out = dict(GOOD, adjusted_disruption_days=9999)
    brief = TierN(memory=FakeMemory(FACTS), llm=fake_llm(json.dumps(out))).analyze(E1)
    assert brief.adjusted_days == 5 * 4 + 10


def test_llm_outage_falls_back_to_deterministic_brief(monkeypatch):
    monkeypatch.setattr("tier_n.llm.time.sleep", lambda *_: None)
    llm = fake_llm(*[RuntimeError("down")] * 3)
    brief = TierN(memory=FakeMemory(FACTS), llm=llm).analyze(E1)
    assert brief.degraded and brief.facts == FACTS
    assert brief.recommendations == []


def test_action_contradicting_avoid_list_is_blocked():
    out = dict(GOOD, recommendations=GOOD["recommendations"] + [
        {"action": "Place expedited order with Shenzhen Brightline Electronics (S07)", "time_to_effect": "48 hours",
         "est_cost_usd": None, "rationale": "qualified alternate", "evidence": ["M2"]},
    ])
    brief = TierN(memory=FakeMemory(FACTS), llm=fake_llm(json.dumps(out))).analyze(E1)
    assert [r["action"] for r in brief.recommendations] == ["Book air freight today"]
    assert len(brief.blocked) == 1 and "Brightline" in brief.blocked[0]


# ---- ledger ----------------------------------------------------------------------
def test_ledger_acceptance_rates(tmp_path):
    p = tmp_path / "log.jsonl"
    ledger.record("E1", "a", False, False, path=p)
    ledger.record("E1", "b", True, True, path=p)
    ledger.record("E1", "c", True, True, path=p)
    stats = {s["mode"]: s["rate"] for s in ledger.acceptance_by_event(path=p)}
    assert stats == {"no memory": 0.0, "with memory": 1.0}
