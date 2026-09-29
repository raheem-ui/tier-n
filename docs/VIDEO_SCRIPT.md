# Demo video script (target 3:30, hard max 5:00)

Record with OBS or Loom at 1080p, browser zoom 110%. Run `python scripts/seed.py` right before recording.
Upload to **YouTube** (unlisted or public). No Drive links. Don't name the event/competition anywhere, including the title, description and tags.

| Time | Screen | Say (roughly) |
|---|---|---|
| 0:00-0:20 | Title card / app header | "I'm Raheem. I work in supply-chain risk. This is Tier-N, a risk analyst agent that remembers every supplier incident, what fixed it, and how the analyst using it likes to work. It's built on Hindsight for memory and Groq for the LLM." |
| 0:20-0:45 | Event dropdown on E1 Typhoon | "Here's the problem. A typhoon warning for Kaohsiung: the port is closed for about 5 days. Our capacitor supplier has 6 days of inventory. On paper we're fine." |
| 0:45-1:30 | Click **Analyze**; pan the LEFT column | "Here's a capable LLM without memory. It says $0 at risk because the buffer covers it, and it suggests shifting volume to Brightline, our qualified alternate. That's reasonable and wrong on both counts." |
| 1:30-2:20 | RIGHT column; open "Why?" chips | "Same model, same prompt, but now it recalls from Hindsight. The last time this port closed, the backlog added 5 days, so the disruption is really 10 days and $1.9M is at risk. That's M1. Air freight worked for $180k (M2), and cargo space sells out within 24 hours of a warning (M11), so book it today. And Brightline failed an audit in March with an open CAPA (M9), so avoid them. Every claim is cited and every dollar is computed, not generated." |
| 2:20-2:45 | 👍 air freight; 👎 a weak one with a reason | "I give feedback, and it's retained as memory, not just logged." |
| 2:45-3:05 | Type the Penang correction; **Remember this** | "Now I teach it something new: Penang, our go-to backup, has a labor dispute." |
| 3:05-3:40 | Switch to E2 Power rationing; Analyze (have a pre-recorded "before correction" clip ready to cut in) | "Three days later, power rationing hits the same capacitor supplier. Before my correction, its plan was air freight plus Penang's consignment stock. Now Penang is on the avoid list next to Brightline, and air freight is the plan. I didn't touch a prompt. I just told it, like you'd tell a colleague." |
| 3:40-4:00 | **Ask memory** tab: "Which alternate capacitor suppliers are safe right now?" | "I can also ask it anything. This is Hindsight reflect, reasoning over everything it has learned." |
| 4:00-4:20 | **Learning** tab chart | "Takeaway: the model is the same on both sides. Memory is what turns a generic assistant into something that knows your history. That's what this adds." |

**Backup plan:** if a live call is slow, cut the wait in editing. Record each segment separately so a flaky take only costs one segment.
