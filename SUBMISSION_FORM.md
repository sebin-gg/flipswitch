# 📝 Hackathon Submission — Portal Answers

Copy-paste source for the WeMakeDevs / DevTools Academy submission form.

---

## 1. Project title

**Switch ADR Architect — Multiplayer Architecture Decision Records in Team Chat**

One-line description: *A Switch agent that turns team chat debates into committed Git ADRs.*

## 2. Track

**Business Workflow**

It is a team tool: engineering workflow, Git-native records, B2B framing.

## 3. Repo link

**<https://github.com/sebin-gg/flipswitch>**

Public. `README.md` §5 covers Switch registration, room UUID and the run command; §6 runs the whole
standalone stack locally and reproduces the `#adr-review-live` transcript;
[`docs/LIVE_SWITCH_SETUP.md`](docs/LIVE_SWITCH_SETUP.md) §7 documents custom-agent registration,
channel-bridged rooms and the addressing policy. [`switch-template.yaml`](switch-template.yaml)
describes the agent, its room and its addressing policy for a Console install.

## 4. Demo video link

Published as public release assets (no login, direct playback):

* Music version — <https://github.com/sebin-gg/flipswitch/releases/download/demo-video/flipswitch-demo-60s-music.mp4>
* Narration only — <https://github.com/sebin-gg/flipswitch/releases/download/demo-video/flipswitch-demo-60s-narrated.mp4>
* Live-room cut (silent, captioned) — <https://github.com/sebin-gg/flipswitch/releases/download/demo-video/flipswitch-live-mattermost.mp4>

The first two are **60.000s**, 1800 frames, 1280×720, captioned. The third is **34.7s** and rendered
from the real `#adr-review-live` transcript recorded against the local Switch + Mattermost stack
(no narration; no screen capture). Release page:
<https://github.com/sebin-gg/flipswitch/releases/tag/demo-video>.

> **If the form requires YouTube/Loom:** upload `demo_video/flipswitch-demo-60s-music.mp4`
> (already 60s, under 3 min) as unlisted and paste that link instead.

## 5. What the project does, who it's for

Turns a team's architecture debate in chat into a committed MADR record. The agent joins the room
through Switch, reads the discussion, then checks the decision against the guardrails chat usually
skips: no rollback or mitigation plan, no stated trade-offs, no evidence for the benefits it claims.
It asks for whatever is missing in the thread, waits for a teammate, and only then writes the ADR
into `docs/adr/` and commits it to git. Alternatives the team mentioned are recorded with the rest —
it does not prompt for those yet.

Built for engineering teams, tech leads and platform/infrastructure groups who decide in Slack,
Mattermost or Discord but rarely write ADRs, and who want the decision to outlive the conversation
without adopting another documentation tool.

## 6. Agent + chat platform connected via Switch

**Custom Python agent — not Claude Code or Codex.** It speaks Switch's protocol directly: SSE
`/agents/{id}/events` with `Last-Event-ID` resume, a 2s heartbeat, and the `connect_to_room`,
`read_context`, `post_message` and `list_rooms` operations.

**Chat side: Mattermost** (the bridge bundled with Switch) is the documented target. There is no
channel-specific code in the agent — the Python sources contain no Slack/Discord/Mattermost/Teams
strings at all — so the room's channel comes entirely from whichever bridge Switch is running.

**Verified against a real stack, not only the simulator.** A standalone Switch deployment
(`switch-core` + the bundled Mattermost 11.9, run on WSL2/Docker) was provisioned locally; the agent
was registered as a custom client with `POST /agents` (`connector_type: custom`,
`connection_model: always_on`), the Mattermost channel `#adr-review-live` was bridged into the room
`18b14137-b31e-4544-9b28-9bb4fa2ad1d3`, and it answered a teammate's `@architect` mention, asked for
the missing rollback plan, then posted `Decision recorded` and committed
`docs/adr/0002-i-propose-postgres-16-with-timescaledb-mature-operators.md` in a scratch clone. That
conversation is reproduced word-for-word in the README, and getting there surfaced two real defects
that are fixed in the repo: a claim sent before the SSE stream registered (409/400, silent), and
title truncation mid-word.

Caveat on the video only: the 60s cut is rendered from `python main.py --simulate` so it needs no
Docker or network, and was not screen-captured from the hosted room. The live-room evidence in the
repo is the transcript, the room UUID and the generated ADR.

Also note: `switch-template.yaml` describes the agent, room and addressing policy for a Console
install with a selectable runtime (`custom`/`python` among them); it does not launch this Python
client, which is started separately against the bridge.

## 7. What I liked about Switch / what I'd improve

**Liked**

* Agents as first-class room members. One agent, several humans, shared context — the thing
  terminal-bound agents structurally cannot do.
* A small, readable HTTP surface. SSE with cursor resume, a 2s heartbeat, and four ops calls were
  enough to build a real client without an SDK.
* Addressing as a first-class concept (owner-only → `anyone_in` room), and declarative room +
  agent setup in `switch-template.yaml`: addressing, channel type and kickoff message are
  configuration, not prose.
* Channel-agnostic by construction: the agent code never mentions Mattermost, Slack or Discord.

**Would improve**

* Docs friction that cost real time: registration token vs agent API key, the returned `id` not
  matching the display name, and finding a room's UUID only via `list_rooms`.
* The silent trap: new agents start owner-only, so a connected agent looks broken because it ignores
  teammates until addressing is widened. Surface that in the install output.
* Ship a reference mock bridge. We wrote one — an embedded bridge plus a strict test harness that
  rejects unexpected operation arguments — because testing against a live room was the slowest part
  of the loop; every team will otherwise write their own.
* Tighter error bodies, and a state table for heartbeat 404/409 plus reconnect/cursor handling.

---

## Supporting detail for judges

### How Switch is used

* **SSE downstream**: `GET /agents/{id}/events` with a client-generated connection id, `scope=all`,
  and cursor resume via `Last-Event-ID`.
* **Heartbeat and liveness**: `POST /agents/{id}/connection/beat` every 2 seconds; a 404/409 reopens
  the stream per the protocol.
* **Room claim**: `connect_to_room` resolves the room and binds subsequent operations to it.
* **Context retrieval**: `read_context` returns the room's thread-shaped timeline; the agent flattens
  it and analyzes the discussion.
* **Bi-directional interaction**: `post_message` asks clarifying questions and reports the committed
  ADR in-thread.
* **Declarative template**: `switch-template.yaml` installs the agent from Switch Console.

### Tech stack

* **Switch** (open-source AI teammate infrastructure by SandboxAQ) — spoken as a protocol client
* **Python 3.11–3.13** (`requests` pinned to 2.34.2, threading, `http.server` mock bridge)
* **MADR 3.0** (Markdown Architectural Decision Records)
* **Git** (autonomous repository version control)
* **OpenAI-compatible LLM** (optional smart synthesis; deterministic heuristic fallback)
* **GitHub Actions** CI: test matrix on 3.11/3.12/3.13 plus a demo smoke run

### How to run (for judges)

```bash
git clone https://github.com/sebin-gg/flipswitch.git
cd flipswitch
pip install -r requirements.txt
python main.py --simulate          # embedded Switch bridge + full demo, no Docker/Postgres
python -m unittest test_e2e.py -v  # 7 tests incl. protocol contract, claim race, duplicate-ADR guards
```

Expected: the demo prints the room conversation, the agent's clarifying question, the teammate's
rollback answer, and a new MADR file committed to `docs/adr/`.

### Judging alignment

| Criterion | Where it shows |
|:--|:--|
| Switch centrality (30%) | SSE `/events`, heartbeat, `connect_to_room`, `read_context`, `post_message`; no fallback bot API |
| Technical execution / reproducibility (25%) | 7 passing E2E tests, CI on three Python versions, zero-dependency simulator, graceful LLM fallback |
| Creativity / impact (25%) | Turns ephemeral chat consensus into durable, indexed, versioned architecture memory |
| Presentation / docs (20%) | README architecture + protocol notes, 30s/60s narrated demo cuts, blog post |

### Optional side tracks

* **Blog**: [`BLOG_POST.md`](BLOG_POST.md) → publish and submit the link.
* **#HowISwitch post**: draft around the "chat is where decisions happen, Git is where they survive"
  angle and link the repo + blog.
