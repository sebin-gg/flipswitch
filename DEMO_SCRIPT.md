# 🎬 Switch ADR Architect — Demo Video Script (75 Seconds)

> **Target Duration:** 60–90 seconds  
> **Resolution:** 1080p (1920x1080) or 2K  
> **Audio:** Clear voiceover / narration  

---

## ✅ Pre-flight (5 minutes before recording)

```bash
pip install -r requirements.txt
python -m unittest test_e2e.py -v   # confirm 3/3 green
python main.py --list-models        # show heuristic or smart model
```

Decide which take you want:
* **Embedded demo (recommended, 100% reproducible):** `python main.py --simulate` — opens a mock Switch bridge, shows the team chat in the terminal, commits the ADR to `docs/adr/`.
* **Live Switch room:** run `python main.py --bridge-url "$BRIDGE_URL" --agent-id architect --api-key "$KEY" --room "<room>"`, then have a teammate post the discussion in Mattermost/Slack. Record the chat window plus the terminal/editor.

If `ADR_API_KEY` is set, the agent prints `smart model gpt-4.1 @ ...`; otherwise it prints the offline engine. Both are valid — say which one is on screen.

---

## 📋 Shot List & Timeline

| Time | Visual / Screen Recording | Narration / Voiceover |
|:---:|:---|:---|
| **0:00 - 0:12** | **Screen:** Open team chat (Mattermost/Discord/Terminal) with active debate about database choice between Alice and Bob.<br>**Graphic:** "The Problem: Architecture decisions in chat disappear into thin air." | *"Engineering teams make huge architectural decisions in chat every single day. But nobody writes the ADR, nobody documents the rollback strategy, and within months, context is lost forever."* |
| **0:12 - 0:25** | **Screen:** Show Switch Console or Switch Architecture Diagram.<br>**Visual:** Highlighting Switch's bidirectional bridge connecting chat rooms to local agents. | *"Meet **Switch ADR Architect**, built for the 'Flip the Switch' hackathon. Powered by Switch, this agent doesn't sit isolated in a terminal — it lives right inside your team's room as an active collaborator."* |
| **0:25 - 0:42** | **Screen:** Terminal running `python main.py --simulate` or the live chat window.<br>**Action:** Alice tags `@architect summarize our discussion and draft an ADR` in `#architecture-review`.<br>**Response:** Agent replies in thread: *"I analyzed the team discussion for Selection of Database for System Architecture. Before recording to git, please clarify: 1. What is the rollback or mitigation plan if this decision encounters failure in production?"* | *"Watch it work: Alice asks the agent to summarize their database debate. The agent reads the room through Switch's context operation, notices the missing rollback strategy, and asks the team directly in chat."* |
| **0:42 - 0:58** | **Screen:** Bob replies in chat: *"@architect In case of failure, our rollback strategy is falling back to managed Aurora read-replicas."*<br>**Action:** Agent immediately renders the MADR 3.0 document, updates `docs/adr/README.md`, and commits to git. | *"Bob answers with the rollback plan. The agent folds it into the record, compiles the markdown, indexes it, and commits the accepted decision to git."* |
| **0:58 - 1:12** | **Screen:** Split screen showing the generated Markdown file in `docs/adr/0002-*.md` and `git log` showing `docs(adr): record ADR-0002: ...`.<br>**Visual:** Clean MADR 3.0 formatting with Status, Context, Decision Outcome, Pros/Cons, and Rollback & Failure Strategy. | *"Here is the generated record in `docs/adr/`, formatted to the MADR standard, indexed in the table of contents, and safely recorded in version control."* |
| **1:12 - 1:20** | **Screen:** Title card: **Switch ADR Architect**<br>GitHub URL + "Powered by Switch (SandboxAQ)" | *"With Switch, isolated AI tools become true multiplayer teammates. Turn your team's conversations into durable architectural assets today. Check out the GitHub repo below!"* |

---

## 🎙️ Recording Tips
1. Split terminal or window: Left side team chat (live Mattermost or `python main.py --simulate`), Right side VS Code / file explorer showing `docs/adr/`.
2. When the agent answers and commits, highlight the new file appearing in the explorer.
3. Keep the run deterministic: for the embedded demo, delete the generated `docs/adr/0002-*.md` and its commit (or run from a fresh clone) so the numbering on screen matches this script. You can also just say "a new ADR" if the number differs.
4. Show `python main.py --list-models` once if you want to make the smart-model option visible.
5. Keep pace steady and confident; do not exceed ~90 seconds.
