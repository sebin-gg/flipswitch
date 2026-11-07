# 📝 Hackathon Submission Form Details

Use the sections below to complete your submission on the WeMakeDevs / DevTools Academy portal.

---

### Project Name
**Switch ADR Architect: Multiplayer Architecture Decision Records in Team Chat**

### Track
* **Best Business Workflow**

### Tagline / 1-Sentence Pitch
> Turns casual engineering debates in Slack, Discord, and Mattermost into authoritative, peer-reviewed Git Architecture Decision Records (ADRs) using Switch.

---

### Short Project Description (under 250 words)

Engineering teams discuss architecture, databases, and API choices in team chat every day, but formal Architecture Decision Records (ADRs) are rarely written. Context evaporates, trade-offs are forgotten, and rollback strategies are never documented.

**Switch ADR Architect** bridges this gap by bringing an AI architect directly into team chat rooms via **Switch**. When invoked (`@architect summarize and draft ADR`), the agent reads the conversation through Switch's `read_context` operation, synthesizes the debate, and detects architectural gaps — a missing rollback plan, unstated maintenance trade-offs, or an unexamined alternative.

The agent asks clarifying questions in the thread and waits for a teammate. Once answered, it generates a standard MADR 3.0 record, updates `docs/adr/README.md`, and commits the decision to Git with a clean conventional commit. A smarter LLM-backed engine handles synthesis when an API key is configured; a deterministic offline engine keeps the demo and tests reproducible with zero setup.

Switch is the indispensable core: it supplies the room topology, addressing, shared multi-human context, and the operations the agent acts through. Without Switch this would be another single-user terminal tool rather than a multiplayer teammate.

---

### How Switch is Used

* **SSE downstream**: `GET /agents/{id}/events` with a client-generated connection id, `scope=all`, and cursor resume via `Last-Event-ID`.
* **Heartbeat and liveness**: `POST /agents/{id}/connection/beat` every 2 seconds; a 404/409 reopens the stream per the protocol.
* **Room claim**: `connect_to_room` resolves the room and binds subsequent operations to it.
* **Context retrieval**: `read_context` returns the room's thread-shaped timeline; the agent flattens it and analyzes the discussion.
* **Bi-directional interaction**: `post_message` asks clarifying questions and reports the committed ADR in-thread.
* **Declarative template**: `switch-template.yaml` installs the agent from Switch Console.

---

### Tech Stack
* **Switch** (open-source AI teammate infrastructure by SandboxAQ)
* **Python 3.10+** (`requests` SSE client, threading, `http.server` mock bridge)
* **MADR 3.0** (Markdown Architectural Decision Records)
* **Git** (autonomous repository version control)
* **OpenAI-compatible LLM** (optional smart synthesis; heuristic fallback)
* **Supported chat apps**: Mattermost, Slack, Discord, Microsoft Teams

---

### How to Run (for judges)

```bash
git clone https://github.com/sebin-gg/flipswitch.git
cd flipswitch
pip install -r requirements.txt
python main.py --simulate          # embedded Switch bridge + full demo, no Docker/Postgres
python -m unittest test_e2e.py -v  # 6 tests incl. protocol + duplicate-ADR guards
```

Expected: the demo prints the room conversation, the agent's clarifying question, the teammate's rollback answer, and a new MADR file committed to `docs/adr/`.

---

### Public Repository
* GitHub: `https://github.com/sebin-gg/flipswitch`

### Demo Video Link
* **TODO before submitting:** record `python main.py --simulate` (or the live Mattermost room) and paste the YouTube/Loom link here.
* Script and shot list: [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md)

---

### Judging Alignment

| Criterion | Where it shows |
|:--|:--|
| Switch centrality (30%) | SSE `/events`, heartbeat, `connect_to_room`, `read_context`, `post_message`; no fallback bot API |
| Technical execution / reproducibility (25%) | 3 passing E2E tests, zero-dependency simulator, portable test sandbox, graceful LLM fallback |
| Creativity / impact (25%) | Turns ephemeral chat consensus into durable, indexed, versioned architecture memory |
| Presentation / docs (20%) | README architecture + protocol notes, 75-second demo script, blog post |

---

### Optional Side Tracks
* **Blog**: [`BLOG_POST.md`](BLOG_POST.md) → publish and submit the link.
* **#HowISwitch post**: draft around the "chat is where decisions happen, Git is where they survive" angle and link the repo + blog.
