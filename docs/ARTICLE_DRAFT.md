<!-- Draft: ~1,100 words. Edit it into your own voice. Each teammate must publish their OWN article (different angle). Never name the event/competition anywhere, hashtags included: that disqualifies the piece. -->

**Title options**
1. I gave my supply-chain agent a memory. It stopped telling me $0 was at risk
2. The same LLM, twice: what long-term memory changes in a risk analyst agent
3. Why my AI risk analyst needed to remember a typhoon from 2024
4. Stateless agents give generic advice. Here's how I made mine learn from its analyst

---

# I gave my supply-chain agent a memory. It stopped telling me $0 was at risk

A typhoon warning goes out for Kaohsiung. The port will close for about five days. Our main capacitor supplier is there, and we hold six days of their inventory.

I asked a capable LLM what to do. It said, sensibly, that our buffer covers the closure, so revenue at risk is $0. Monitor the situation, and if needed shift volume to our qualified alternate.

Anyone who has done this job for a few years knows that answer is wrong. Not because the model is bad at reasoning, but because it doesn't know what happened last time.

So I built **Tier-N**, a supply-chain risk agent with long-term memory, to see how much of that experience you can give an agent. Short answer: most of it, if you're careful about what goes in and how it comes out.

## What "last time" actually contains

The second answer, the one an experienced analyst gives, draws on four kinds of memory:

1. **History.** The last time this port closed for 4 days, the backlog added 5 more, and shipments arrived 9 days late.
2. **Outcomes.** Air-freighting 40% of volume saved the product line then, at a cost of $180k.
3. **Current state.** The "qualified alternate" failed a quality audit in March, and the corrective action is still open.
4. **Preferences.** This analyst wants dollar impact first, actions ranked by speed, and no "monitor the situation."

None of that is in the model's weights, and it won't fit in a system prompt once you have hundreds of suppliers. It has to be *remembered*: stored as it happens, and retrieved when it's relevant.

## Architecture

Tier-N uses [Hindsight](https://hindsight.vectorize.io/) as its memory layer and Groq for inference. The loop is:

- **Retain** everything with a date: seeded history, every event it analyses, every accept/reject the analyst clicks, and free-text corrections.
- **Recall** evidence for a new event. Hindsight runs semantic, keyword, entity-graph and temporal search in parallel, and I anchor the query to the event's date.
- **Generate** a brief where every claim has to cite a numbered memory.
- **Recompute** the numbers deterministically.

Seeding history looks like this:

```python
client.retain_batch(bank_id=bank, items=[{
    "content": h["content"],
    "context": f"Northwind supply-chain {h['kind']} record",
    "timestamp": datetime.fromisoformat(h["date"]),
    "entities": [{"text": catalog[s]["name"]} for s in h["suppliers"]],
    "tags": [h["kind"]] + [f"supplier:{s}" for s in h["suppliers"]],
} for h in history])
```

The timestamps and entities matter. Temporal recall is what lets "the most recent audit wins" work. Entity links are what connect "Brightline" in an audit record to "Brightline" as a listed alternate in a live event.

For a new event I run two recalls and merge them. The first is event-specific (this port, these suppliers, their alternates). The second is about the analyst ("her preferences, bans and lessons learned"). One query tends to bury preferences under incident history.

## Rule 1: the LLM doesn't get to do the math

The most important design choice was **what the model is not allowed to do**. It never outputs revenue figures. It can only propose an *adjusted disruption length* and must cite the memory that justifies it:

```python
adjusted = _clamp_days(out.get("adjusted_disruption_days"), announced)
exposure = compute_exposure(event["affected_suppliers"], adjusted)
```

In the typhoon case, memory M1 ("real delay is roughly closure length plus 5 days of backlog") moves the disruption from 5 to 10 days. A 6-day buffer then leaves a 4-day gap, and the exposure function computes **$1.89M** at risk. The number is traceable, repeatable, and can't be made up.

## Rule 2: every claim cites a memory, and fake citations are removed

Memories go into the prompt as `[M1] (2024-07-26) ...`, and each recommendation has to list its evidence labels. Models do occasionally cite a label that doesn't exist, so the agent removes any citation that doesn't match a recalled memory. In the UI, every recommendation has "Why?" chips that open the exact memory text and date.

## Before and after

Same model, same prompt, same event. The only difference is whether the memory block is empty.

| | No memory | With memory |
|---|---|---|
| Disruption | 5 days | 10 days (backlog history) |
| Revenue at risk | $0 | $1.89M |
| First action | Monitor, contact supplier | Book air freight **today** (~$180k); cargo sells out within 24h of a warning |
| Alternate | Shift to Brightline | Avoid Brightline: open CAPA from March audit |

## The part that surprised me: feedback as memory

I expected history to be the killer feature. It turned out to be **feedback**. Every time the analyst accepts or rejects a recommendation, Tier-N retains a sentence like *"Tier-N recommended X. Maya rejected it. Her reason: ..."*. When she types a correction ("Penang has a labor dispute, don't rely on them"), it's retained with a timestamp and a "supersedes older memories" context.

Three days later, power rationing hits the same capacitor supplier. The previous brief would have pulled Penang's consignment stock. The new one puts Penang on the avoid list, next to the supplier with the open audit, and falls back to air freight, without being told again. The analyst never touched a config file, rule engine or prompt. She just talked to it, the way you'd correct a junior colleague.

## Lessons learned

- **Timestamps are not optional.** Without dates, "failed an audit" and "passed re-audit" are equally true. With them, recall plus a "latest wins" directive resolves the conflict.
- **Split recall by purpose.** One query for the situation and one for the person was noticeably better than one big query.
- **Keep numbers out of the LLM.** Let memory change the *inputs* to your math, never the outputs.
- **Make memory visible.** Showing the evidence behind each claim is what makes a risk analyst trust the output enough to act on it.
- **Build for failure.** Groq rate limits and malformed JSON are real. Tier-N retries with a repair prompt. If the LLM stays down, it still shows the deterministic exposure and the raw memories.

## Try it

The code is on GitHub: [link]. It runs with a free Groq key and a Hindsight bank, and ships with a fully synthetic company, suppliers and incident history, so you can reproduce the before/after in a couple of minutes.

The model was identical on both sides of that table. The difference between a generic answer and one you can act on was memory.
