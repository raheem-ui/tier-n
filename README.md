# Tier-N: a supply-chain risk analyst that remembers

When a typhoon heads for Kaohsiung, a stateless AI copilot tells you to "monitor the situation and consider alternate suppliers."
A 10-year risk analyst tells you something like this:

> "Last time the port was shut for 4 days, our capacitors arrived 9 days late because of the backlog.
> Air-freighting 40% of volume saved the Aurora line for $180k. Book it **today**, because cargo space sells out within 24h of a warning.
> Don't shift volume to Brightline: their CAPA from the March audit is still open."

**Tier-N** is an agent that gets to that second answer by remembering. It uses [Hindsight](https://hindsight.vectorize.io/) to keep a long-term memory of every supplier incident, every mitigation and what it cost, every audit, and every time the analyst accepted, rejected or corrected one of its recommendations.

> All companies, suppliers and incidents in this repo are **synthetic** (fictional "Northwind Devices").

## Demo in one picture

| | No memory | With memory |
|---|---|---|
| Disruption length | 5 days (as announced) | **10 days**: past Kaohsiung closures added ~5 days of backlog [M1] |
| Revenue at risk | **$0**: "inventory buffer covers it" | **$1.89M** across Aurora + Nimbus lines |
| Top action | "Monitor and contact suppliers" | "Book air freight for 40% of MLCC volume **today** (~$180k)" [M2, M11] |
| Alternates | "Shift to qualified alternate Brightline" | ⛔ Avoid Brightline: open CAPA-2291 [M9]. Use Penang consignment stock [M6] |

Then the analyst teaches it something new ("Penang MicroParts has a labor dispute, so don't rely on them"), and the **next** brief reflects that without being asked.

## How memory is used

```
            ┌──────────────── Hindsight bank "northwind-supply-risk" ────────────────┐
 seed  ───► │ incidents · decisions+outcomes · audits · analyst preferences (dated)   │
 event ───► │ every analysed event (retain, async)                                    │
 👍/👎  ───► │ every accept/reject + the analyst's reason                              │
 teach ───► │ free-text corrections (tagged "correction", latest wins)                │
            └───────▲─────────────────────────────────────────────▲──────────────────┘
                    │ recall (semantic+BM25+graph+temporal,        │ reflect
                    │ anchored to event date)                      │ "Ask memory" tab
          ┌─────────┴─────────┐    numbered facts [M1..Mn]    ┌─────┴─────┐
 event ──►│ Tier-N agent      │──────────────────────────────►│ Groq LLM  │──► JSON brief
          │ exposure math     │◄──────────────────────────────│           │
          └───────────────────┘  adjusted days + citations    └───────────┘
                    │
                    ▼  recompute $ at risk deterministically, drop invalid citations
               Streamlit UI: side-by-side brief · evidence chips · feedback · learning chart
```

| Hindsight feature | Where | Why |
|---|---|---|
| `create_bank` with mission, disposition (skepticism 4) and `retain_mission` | `tier_n/memory.py` | Extraction focuses on suppliers, costs, durations, audit status and bans |
| `create_directive` | `memory.py` | Hard rules: quantify in USD, only cite stored history, latest memory wins |
| `retain_batch` with `timestamp`, `entities`, `tags`, `document_id` | `seed_history()` | Dated, entity-linked history for temporal and graph recall |
| `recall` with `query_timestamp` | `recall_for_event()` | Two queries (event-specific + analyst preferences), merged and numbered for citation |
| `retain` (async) | `retain_event()` | Every event becomes part of history |
| `retain` feedback/corrections | `retain_feedback()`, `retain_correction()` | This is how the agent learns from the analyst |
| `reflect` | `ask()` | Free-form Q&A over everything learned |

## Design decisions

- **The LLM never invents dollar figures.** It may only propose an *adjusted disruption length*, backed by a cited memory. `tier_n/exposure.py` recomputes revenue at risk deterministically. The adjustment is clamped so it can't be absurd.
- **Guardrail on contradictions.** If the brief says to avoid a supplier, any action that names that supplier is removed deterministically and shown as blocked.
- **Recall is split by purpose:** one query for the event, one per qualified alternate, and one for the analyst's preferences. Without that, new memories about one supplier crowded out another supplier's open audit. Near-duplicate extracted facts are merged (word-overlap dedupe).
- **Every claim is traceable.** Memories are numbered `[M1..Mn]`, and the agent must cite them. Citations that don't match a recalled memory are removed before rendering.
- **Degrades instead of crashing.** Groq errors (rate limits, `json_validate_failed`, malformed JSON) are retried with a repair prompt. If the LLM stays down, you still get the deterministic exposure view plus the raw memories. If Hindsight is down, you get the memory-less brief and a clear error.
- **Same prompt, memory on or off.** The comparison is fair: the only difference is whether the memories block is empty.
- **Hindsight calls run on a dedicated event loop**, so the async SDK works reliably across Streamlit's rerun threads.

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # add HINDSIGHT_BASE_URL, HINDSIGHT_API_KEY, GROQ_API_KEY
python scripts/seed.py            # builds the memory bank (re-run any time to reset the demo)
streamlit run app.py
```

Terminal-only check: `python scripts/run_demo.py E1`. Offline tests (no keys needed): `pytest -q`.

## Demo script (2 min)

1. **E1 Typhoon**: *Analyze* with comparison on. The left side says $0; the right side says $1.89M, book air freight today, avoid Brightline. Open the "Why?" chips.
2. 👍 the air-freight action; 👎 anything generic, with a reason.
3. **Teach Tier-N:** "Penang MicroParts announced a labor dispute starting Sept 23. Don't rely on them for extra volume or consignment stock until it's resolved."
4. **E2 Power rationing in southern Taiwan** (hits Formosa again, 3 days later): before the correction, Tier-N's plan was air freight plus Penang's consignment stock. After it, Penang moves to ⛔ Avoid (labor dispute) next to Brightline (open CAPA), and air freight is the plan. No prompt or config was changed.
5. **Ask memory:** "Which alternate capacitor suppliers are safe right now?"
6. **Learning tab:** acceptance rate, memory vs no memory.

## Repo layout

```
app.py                 Streamlit UI
tier_n/agent.py        prompt, brief assembly, citation cleaning, fallback
tier_n/memory.py       all Hindsight calls
tier_n/exposure.py     deterministic revenue-at-risk math
tier_n/llm.py          Groq JSON wrapper with retry + repair
tier_n/ledger.py       local feedback log for the learning chart
data/                  synthetic suppliers, history, live events
scripts/               seed/reset, terminal demo
tests/                 offline tests with fake clients
```
