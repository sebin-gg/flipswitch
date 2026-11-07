# 📝 Hackathon Submission Form Details

Use the sections below to complete your submission on the WeMakeDevs / DevTools Academy portal.

---

### Project Name
**Switch ADR Architect: Multiplayer Architecture Decision Records in Team Chat**

### Track
* **Best Business Workflow** (or Wildcard)

### Tagline / 1-Sentence Pitch
> Turns casual engineering debates in Slack, Discord, and Mattermost into authoritative, peer-reviewed Git Architecture Decision Records (ADRs) using Switch.

---

### Short Project Description (under 250 words)
Engineering teams discuss architecture, databases, and API choices in team chat every day, but formal Architecture Decision Records (ADRs) are rarely written. Context evaporates, trade-offs are forgotten, and rollback strategies are never documented.

**Switch ADR Architect** bridges this gap by bringing an autonomous AI architect directly into team chat rooms via **Switch**. When invoked (`@architect summarize and draft ADR`), the agent reads the conversation history using Switch's context API, synthesizes the debate, and automatically detects architectural gaps—such as missing rollback plans, unstated maintenance trade-offs, or unexamined alternatives. 

The agent actively asks clarifying questions to teammates directly in the chat thread. Once clarified by a team member, it generates a standard MADR 3.0 (Markdown Architectural Decision Record), updates the repository's `docs/adr/README.md` index table, and commits the decision directly to git with a clean conventional commit.

Switch is the indispensable core of the system: it transforms what would otherwise be a single-user terminal agent into a multiplayer teammate that shares room context, listens to multi-human discussions, and performs persistent actions on behalf of the engineering team.

---

### How Switch is Used
* **SSE Downstream Transport**: Implements Switch Wire Protocol v6 to subscribe to real-time chat room events (`GET /agents/{id}/stream`).
* **Heartbeat & Liveness**: Sends automated heartbeat frames (`POST /agents/{id}/connection/beat`) to maintain connection state.
* **Context Retrieval**: Uses Switch's `read_context` operation to inspect thread history and multi-participant discussion.
* **Bi-directional Interaction**: Uses Switch's `post_message` operation to ask clarifying questions and confirm git commits.
* **Declarative Template**: Ships with an official Switch Agent Template (`switch-template.yaml`) for 1-click installation via Switch Console.

---

### Tech Stack
* **Switch** (Open-source AI teammate infrastructure by SandboxAQ)
* **Python 3.10+** (SSE client, HTTP operations, ThreadingHTTPServer)
* **MADR 3.0** (Markdown Architectural Decision Records specification)
* **Git** (Autonomous repository version control)
* **Supported Chat Apps**: Mattermost, Slack, Discord, Microsoft Teams

---

### Public Repository
* GitHub: `https://github.com/your-username/flipswitch`

### Demo Video Link
* YouTube / Loom: `[Your recording link here]`
