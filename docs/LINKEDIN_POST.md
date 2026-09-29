<!-- Never name the event/competition, hashtags included. Post AFTER the article is live and paste its link. -->

I asked an LLM what a 5-day typhoon closure at Kaohsiung would cost us. It said $0: we have 6 days of inventory.

Then I gave the same model a memory, and it said $1.89M.

Last time that port closed, the backlog added 5 days. Air freight saved the line for $180k. Cargo space sells out within 24 hours of a warning. And the "qualified alternate" failed an audit in March.

I built Tier-N, a supply-chain risk agent that remembers, using Hindsight for long-term memory and Groq for inference. What I learned:

→ Memory changed the inputs to the math, not the math. The LLM can only adjust the disruption length and must cite why. Dollar figures are computed deterministically.
→ Every claim cites a numbered memory, and made-up citations are removed before anything is shown.
→ Timestamps turn conflicting facts ("failed audit" vs "re-qualified") into a clear answer: the latest wins.
→ Two recalls beat one: one for the situation, one for the analyst's preferences.
→ The biggest win was feedback. Accepts, rejects and plain-English corrections are retained, so the next brief changes without anyone editing a prompt.

Same model on both sides. The difference was memory.

Write-up with code: [article link]
Repo: [GitHub link]

#AIagents #SupplyChain #RiskManagement #LLM #AgentMemory
