# 🎬 Switch ADR Architect — Demo Video Script (75 Seconds)

> **Target Duration:** 60–90 seconds  
> **Resolution:** 1080p (1920x1080) or 2K  
> **Audio:** Clear voiceover / narration  

---

## 📋 Shot List & Timeline

| Time | Visual / Screen Recording | Narration / Voiceover |
|:---:|:---|:---|
| **0:00 - 0:12** | **Screen:** Open team chat (Mattermost/Discord/Terminal) with active debate about database choice between Alice and Bob.<br>**Graphic:** "The Problem: Architecture decisions in chat disappear into thin air." | *"Engineering teams make huge architectural decisions in chat every single day. But nobody writes the ADR, nobody documents the rollback strategy, and within months, context is lost forever."* |
| **0:12 - 0:25** | **Screen:** Show Switch Console or Switch Architecture Diagram.<br>**Visual:** Highlighting Switch's bidirectional bridge connecting chat rooms to local agents. | *"Meet **Switch ADR Architect**, built for the 'Flip the Switch' hackathon. Powered by Switch, this agent doesn't sit isolated in a terminal — it lives right inside your team's room as an active collaborator."* |
| **0:25 - 0:42** | **Screen:** Terminal running `python main.py --simulate` or live chat.<br>**Action:** Alice tags `@architect summarize our discussion and draft an ADR` in `#architecture-review`.<br>**Response:** Agent replies in thread: *"I analyzed the discussion on PostgreSQL vs TimescaleDB. Before committing to git, what is our rollback plan if migration fails?"* | *"Watch it work: When Alice asks the agent to summarize their database debate, Switch ADR Architect uses Switch's context API to read the room history. It notices critical gaps — like a missing rollback strategy — and asks the team directly in chat."* |
| **0:42 - 0:58** | **Screen:** Bob replies in chat: *"@architect In case of failure, our rollback plan is falling back to Aurora read-replicas."*<br>**Action:** Agent immediately generates MADR 3.0 document, updates `docs/adr/README.md`, and commits to git with a message. | *"Bob replies with the rollback plan. The agent updates the MADR draft, compiles the markdown, and autonomously commits the accepted decision right into git with a clean commit history."* |
| **0:58 - 1:12** | **Screen:** Split screen showing the generated Markdown file in `docs/adr/0001-*.md` and `git log` showing the commit.<br>**Visual:** Clean MADR 3.0 formatting with Deciders, Context, Decision, Pros, Cons, and Rollback. | *"Here is the generated record in `docs/adr/`, formatted to the MADR standard, indexed in the table of contents, and safely recorded in version control."* |
| **1:12 - 1:20** | **Screen:** Title card: **Switch ADR Architect**<br>GitHub URL + "Powered by Switch (SandboxAQ)" | *"With Switch, isolated AI tools become true multiplayer teammates. Turn your team's conversations into durable architectural assets today. Check out the GitHub repo below!"* |

---

## 🎙️ Recording Tips
1. Split terminal or window: Left side team chat (or `python main.py --interactive`), Right side VS Code / file explorer showing `docs/adr/`.
2. When the agent answers and commits, highlight the new file appearing in the explorer.
3. Keep pace steady and confident.
