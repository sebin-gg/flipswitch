# 🚀 Why AI Agents Belong in Team Chat: Building Switch ADR Architect

*By Sebin — Built for the "Flip the Switch" Hackathon (WeMakeDevs × DevTools Academy)*

---

### The Terminal Prison of AI Agents

Over the past year, developer tooling has experienced an explosion of autonomous coding agents: Claude Code, Cursor, Copilot CLI, and Antigravity. They are brilliant, fast, and capable.

Yet they all suffer from the same architectural limitation: **they are trapped in a single engineer's private terminal.**

Software engineering is inherently collaborative. Systems aren't built in solitary confinement; they are debated, reviewed, and decided in team channels across Slack, Discord, and Mattermost. When a developer uses an isolated terminal agent to draft architecture or code, they are forced to play the role of a human copy-paste bridge—manually shuttling snippets between chat and the terminal.

That is why **[Switch](https://github.com/sandbox-quantum/switch)** (by SandboxAQ) caught my attention during the "Flip the Switch" hackathon.

Switch is open-source infrastructure designed to connect AI agents directly into team chat channels. It turns ordinary messaging channels into shared collaborative "rooms" where humans and agents work side-by-side with shared context.

---

### The Problem: Vanishing Architecture Decisions

Every engineering team has experienced this:

1. Two senior engineers debate database choices in `#engineering`.
2. One advocates for PostgreSQL with TimescaleDB; the other warns about vacuum overhead; an SRE suggests ClickHouse.
3. Consensus is reached in chat: *"Let's go with TimescaleDB, but set up Aurora read-replicas as a fallback."*
4. **Nothing is written down.**

Six months later, a production outage occurs or new engineers join the team. Nobody remembers why ClickHouse was rejected or what the rollback plan was. Traditional Architecture Decision Records (ADRs) are widely recommended, but in reality, nobody wants to leave chat, look up the MADR format, create a branch, and write markdown files.

---

### Enter Switch ADR Architect

For the hackathon, I built **Switch ADR Architect**: an autonomous architecture record agent that lives in your team's chat rooms via Switch.

Here is how the workflow runs:

1. **Ambient Room Listening**: The agent sits in `#architecture-review` through Switch's SSE event bus (`/stream`).
2. **Context Synthesis**: When someone types `@architect summarize our discussion and draft an ADR`, the agent queries Switch's `read_context` operation to parse the multi-human discussion.
3. **The Intelligent Guardrail**: The agent doesn't just blindly summarize. It acts like a real Staff Architect: it scans for missing critical trade-offs. If the team forgot to specify a rollback plan or negative consequences, it asks:
   > *"I analyzed your discussion on TimescaleDB. Before committing to git, what is our rollback plan if migration fails?"*
4. **Real-Time Clarification**: An engineer replies in the thread:
   > *"@architect Fallback is switching DNS to Aurora read-replica."*
5. **Autonomous Git Recording**: The agent incorporates the answer into standard MADR 3.0 format, updates `docs/adr/README.md`, and commits the file directly to git:
   ```bash
   git commit -m "docs(adr): record ADR-0001: Selection of Database for System Architecture"
   ```

---

### How Switch Makes It Possible

Switch ADR Architect is not a stateless webhook bot. It is a genuine teammate powered by Switch's wire protocol:

* **Single Connection, Multi-Human Awareness**: Through Switch, multiple engineers (Alice, Bob, Charlie) interact with one shared agent session without session collisions.
* **Persistent Connection State**: The agent maintains persistent connection IDs and automated 2-second heartbeats (`/connection/beat`) to survive network fluctuations.
* **Open Wire Standards**: Because Switch is open-source and self-hostable, your team's proprietary architecture discussions never leak to third-party bot platforms.

---

### Try It Yourself

The entire project is open-source and designed to run out of the box in 60 seconds with an embedded Switch simulator:

```bash
git clone https://github.com/your-username/flipswitch.git
cd flipswitch
pip install -r requirements.txt
python main.py --simulate
```

Run the automated test suite:
```bash
python -m unittest test_e2e.py
```

### Final Thoughts

The future of AI engineering isn't bigger single-user chat windows—it's multiplayer agents collaborating where teams already live. Huge thanks to **WeMakeDevs**, **DevTools Academy**, and the **Switch AI** team for hosting this challenge!
