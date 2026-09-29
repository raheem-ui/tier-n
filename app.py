"""Tier-N Streamlit UI.  Run:  streamlit run app.py"""
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import streamlit as st

from tier_n import ledger
from tier_n.agent import Brief, TierN, brief_to_markdown
from tier_n.config import settings
from tier_n.data import analyst_name, load_events, products, suppliers_by_id
from tier_n.llm import GroqJSON, LLMError
from tier_n.memory import Memory

st.set_page_config(page_title="Tier-N | supply risk analyst", page_icon="🛰️", layout="wide")
st.markdown(
    """<style>
    .chip{display:inline-block;padding:1px 8px;margin:0 4px 4px 0;border-radius:10px;font-size:0.78rem;
          background:rgba(59,130,246,.15);border:1px solid rgba(59,130,246,.45)}
    .avoid{border-left:3px solid #e5484d;padding:4px 10px;margin:6px 0;background:rgba(229,72,77,.07)}
    .mode-off{color:#8b8b8b;font-weight:600;letter-spacing:.04em}
    .mode-on{color:#3b82f6;font-weight:600;letter-spacing:.04em}
    </style>""",
    unsafe_allow_html=True,
)


@st.cache_resource
def build_agent() -> tuple[TierN, Memory | None, list[str]]:
    problems = []
    llm = None
    try:
        llm = GroqJSON()
    except LLMError as e:
        problems.append(f"LLM: {e}")
    memory = Memory()
    try:
        memory.client.get_bank_config(bank_id=memory.bank_id)
    except Exception as e:
        problems.append(f"Hindsight bank '{memory.bank_id}' not reachable - run `python scripts/seed.py` ({type(e).__name__})")
    return TierN(memory=memory, llm=llm), memory, problems


agent, memory, problems = build_agent()
state = st.session_state
state.setdefault("briefs", {})
state.setdefault("verdicts", {})

# ---- sidebar -----------------------------------------------------------------
with st.sidebar:
    st.header("🛰️ Tier-N")
    st.caption(f"Risk analyst for **Northwind Devices** (synthetic data). Working with **{analyst_name()}**.")
    st.markdown(f"**Memory bank:** `{settings.bank_id}`  \n**LLM:** `{settings.groq_model}`")

    def _key_status(k: str | None) -> str:
        return f"set ({k[:3]}…, {len(k)} chars)" if k else "**missing**"

    st.caption(f"Hindsight key: {_key_status(settings.hindsight_api_key)} · Groq key: {_key_status(settings.groq_api_key)}")
    if memory is not None:
        n = memory.memory_count()
        if n is not None:
            st.metric("Memories stored", n)
    for p in problems:
        st.warning(p)
    st.divider()
    if st.button("↺ Reset demo memory", help="Deletes the bank and re-seeds the history. Takes ~1 min."):
        with st.spinner("Rebuilding memory bank from history..."):
            count = memory.reset()
            ledger.clear()
            state.briefs, state.verdicts = {}, {}
        st.success(f"Re-seeded {count} history records.")

tab_brief, tab_ask, tab_learn = st.tabs(["Disruption brief", "Ask memory", "What Tier-N has learned"])


# ---- rendering helpers ---------------------------------------------------------
def evidence_chips(b: Brief, refs: list[str]) -> None:
    if not refs:
        return
    st.markdown("".join(f"<span class='chip'>{r}</span>" for r in refs), unsafe_allow_html=True)
    with st.expander("Why? (memories cited)", expanded=False):
        for r in refs:
            f = b.fact(r)
            if f:
                st.markdown(f"**{r}** · {f.date or 'undated'} · _{f.type}_  \n{f.text}")


def feedback_controls(b: Brief, event: dict, idx: int, rec: dict) -> None:
    key = f"{b.event_id}-{'on' if b.use_memory else 'off'}-{idx}"
    if key in state.verdicts:
        st.caption("✅ Accepted - remembered" if state.verdicts[key] else "❌ Rejected - remembered")
        return
    c1, c2, c3 = st.columns([1, 1, 4])
    note = c3.text_input("Reason (optional)", key=f"note-{key}", label_visibility="collapsed", placeholder="Why? (optional)")
    for col, accepted, label in ((c1, True, "👍 Accept"), (c2, False, "👎 Reject")):
        if col.button(label, key=f"{label}-{key}"):
            try:
                memory.retain_feedback(event, rec.get("action", ""), accepted, note)
            except Exception as e:
                st.error(f"Could not save to memory: {e}")
                return
            ledger.record(b.event_id, rec.get("action", ""), accepted, b.use_memory)
            state.verdicts[key] = accepted
            st.rerun()


def render_brief(b: Brief, event: dict) -> None:
    label, cls = ("WITH MEMORY", "mode-on") if b.use_memory else ("NO MEMORY", "mode-off")
    st.markdown(f"<span class='{cls}'>{label}</span>", unsafe_allow_html=True)
    st.subheader(b.headline or event["title"])
    if b.degraded:
        st.warning(f"Degraded mode: {b.degraded}")
    m1, m2, m3 = st.columns(3)
    m1.metric("Revenue at risk", f"${b.exposure.total_usd:,}")
    delta = b.adjusted_days - b.announced_days
    m2.metric("Disruption (days)", b.adjusted_days, delta=f"+{delta} vs announced" if delta else None, delta_color="inverse")
    m3.metric("Memories used", len(b.facts))
    if delta:
        st.info(f"**Adjusted from {b.announced_days}d:** {b.adjustment_reason}")
    st.write(b.summary)

    if b.recommendations:
        st.markdown("##### Actions (fastest first)")
    for i, r in enumerate(b.recommendations):
        cost = r.get("est_cost_usd")
        cost_txt = f" · est. ${cost:,}" if isinstance(cost, (int, float)) else ""
        st.markdown(f"**{i + 1}. {r.get('action', '')}**  \n<small>⏱ {r.get('time_to_effect', '?')}{cost_txt}</small>", unsafe_allow_html=True)
        st.caption(r.get("rationale", ""))
        evidence_chips(b, r.get("evidence", []))
        feedback_controls(b, event, i, r)

    for a in b.avoid:
        st.markdown(f"<div class='avoid'>⛔ <b>Avoid:</b> {a.get('what', '')} - {a.get('why', '')}</div>", unsafe_allow_html=True)
        evidence_chips(b, a.get("evidence", []))
    for blocked in b.blocked:
        st.caption(f"🛡️ Guardrail removed an action that contradicted the avoid list: _{blocked}_")
    if b.open_questions:
        st.markdown("##### Open questions")
        for q in b.open_questions:
            st.markdown(f"- {q}")

    with st.expander("Exposure detail"):
        prods = products()
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Supplier": s.supplier_name,
                        "Parts": ", ".join(s.parts),
                        "Products": ", ".join(prods[p]["name"] for p in s.products),
                        "Buffer (d)": s.inventory_days,
                        "Gap (d)": s.gap_days,
                        "At risk ($)": s.revenue_at_risk_usd,
                    }
                    for s in b.exposure.suppliers
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
    st.download_button(
        "Export brief (.md)", brief_to_markdown(b), file_name=f"tier-n-{b.event_id}-{'mem' if b.use_memory else 'nomem'}.md",
        key=f"dl-{b.event_id}-{b.use_memory}",
    )
    st.caption(f"Generated in {b.latency_s:.1f}s")


# ---- tab: brief -----------------------------------------------------------------
with tab_brief:
    events = load_events()
    catalog = suppliers_by_id()
    options = [f"{e['date']} · {e['title']}" for e in events] + ["➕ Custom event"]
    choice = st.selectbox("Incoming disruption", options)
    if choice == "➕ Custom event":
        with st.form("custom"):
            title = st.text_input("Title", "Rail strike halts freight to Kaohsiung port")
            desc = st.text_area("Description", "National rail union announces a strike affecting container rail to Kaohsiung.")
            affected = st.multiselect("Affected suppliers", list(catalog), default=["S01"], format_func=lambda s: f"{s} {catalog[s]['name']}")
            days = st.number_input("Announced disruption (days)", 1, 120, 6)
            date = st.date_input("Date")
            if not st.form_submit_button("Use this event"):
                st.stop()
        event = {"id": f"C-{abs(hash(title)) % 10000}", "date": str(date), "title": title, "description": desc,
                 "affected_suppliers": affected, "expected_disruption_days": int(days)}
    else:
        event = events[options.index(choice)]

    st.caption(event["description"])
    compare = st.toggle("Compare with a memory-less agent", value=True)

    if st.button("Analyze disruption", type="primary"):
        runs = {}
        with st.spinner("Recalling memories and drafting brief..."), ThreadPoolExecutor(max_workers=2) as pool:
            on = pool.submit(agent.analyze, event, True)
            off = pool.submit(agent.analyze, event, False, False) if compare else None
            try:
                runs["on"] = on.result()
            except Exception as e:
                st.error(f"Memory recall failed ({type(e).__name__}: {e}). Showing memory-less brief.")
            if off is not None:
                runs["off"] = off.result()
            elif "on" not in runs:
                runs["off"] = agent.analyze(event, use_memory=False, remember=False)
        state.briefs[event["id"]] = runs

    runs = state.briefs.get(event["id"], {})
    if runs:
        cols = st.columns(2) if len(runs) == 2 else [st.container()]
        order = [k for k in ("off", "on") if k in runs]
        for col, k in zip(cols, order):
            with col, st.container(border=True):
                render_brief(runs[k], event)

        st.divider()
        st.markdown("##### Teach Tier-N")
        st.caption("Tell it something it should know next time - it will be retained and used in future briefs.")
        correction = st.text_area(
            "Correction", key=f"corr-{event['id']}", label_visibility="collapsed",
            placeholder="e.g. Penang MicroParts announced a labor dispute starting Sept 23 - don't rely on them for extra volume or consignment stock until it's resolved.",
        )
        if st.button("Remember this") and correction.strip():
            memory.retain_correction(correction.strip(), event["date"])
            st.success("Retained. Future briefs will take this into account.")

# ---- tab: ask memory -------------------------------------------------------------
with tab_ask:
    st.markdown("Ask anything about Northwind's suppliers. Tier-N answers with Hindsight **reflect** over everything it has learned.")
    examples = [
        "Which alternate capacitor suppliers are safe to use right now, and which should we avoid?",
        "What has worked before when Kaohsiung port closed?",
        f"How does {analyst_name()} like her risk briefs written?",
        "What is our biggest structural single-source risk?",
    ]
    q = st.selectbox("Try one", [""] + examples)
    q = st.text_input("Question", value=q)
    if st.button("Ask", type="primary") and q.strip():
        with st.spinner("Reflecting over memory..."):
            try:
                answer, sources = memory.ask(q.strip())
            except Exception as e:
                st.error(f"Reflect failed: {e}")
            else:
                st.markdown(answer)
                if sources:
                    with st.expander(f"Based on {len(sources)} memories"):
                        for s in sources:
                            st.markdown(f"- {s}")

# ---- tab: learning ---------------------------------------------------------------
with tab_learn:
    stats = ledger.acceptance_by_event()
    if not stats:
        st.info("No feedback yet. Accept or reject recommendations in the brief tab and they show up here.")
    else:
        df = pd.DataFrame(stats)
        df["rate"] = (df["rate"] * 100).round()
        st.markdown("##### Recommendation acceptance rate (%)")
        st.bar_chart(df, x="event_id", y="rate", color="mode", stack=False)
        st.dataframe(df.rename(columns={"event_id": "Event", "mode": "Mode", "rate": "Accepted %"}), hide_index=True)
        st.markdown("##### Feedback log")
        for r in reversed(ledger.rows()[-15:]):
            icon = "👍" if r["accepted"] else "👎"
            st.markdown(f"{icon} **{r['event_id']}** ({'memory' if r['use_memory'] else 'no memory'}) - {r['action']}")
