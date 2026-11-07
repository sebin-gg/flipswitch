# Live Switch setup: register the agent, find the room UUID

This is the manual path for running the ADR Architect against a real Switch
server (self-hosted `switch-core`, or a server Switch Console manages for you).
It assumes the server is already running, a messaging bridge is connected, and
a room exists.

Everything below was checked against the published
[agent protocol](https://docs.switchagents.ai/flintai/switch/internals/agent-protocol),
not against a local mock. `switch_simulator.py` mirrors the same routes, so you
can rehearse these calls offline first.

---

## 0. Use the bridge base URL, not the Gateway URL

Operators reach the Gateway; agents reach the agent bridge. They are usually
different addresses, and a client configured with one cannot use the other.

```bash
export BRIDGE_URL="http://localhost:8000"   # switch-core; your host/port may differ
curl -s "$BRIDGE_URL/health"
```

`GET /health` is public and is the correct probe:

| Result | Meaning |
|:--|:--|
| `200` with a healthy body | This is the bridge base URL |
| `401` | Right host, wrong path — you are probably pointed at the Gateway |
| Connection refused | Wrong scheme, host, or port |

---

## 1. Get a registration token

A registration token is **not** an API key. It authenticates registration once
and is rejected everywhere else: an API key cannot register an agent, and a
registration token cannot open a stream.

* **Self-hosted from source:** run `just init-env`. It writes
  `AGENT_REGISTRATION_TOKEN` into `.env` with a generated value.
* **Standalone / Helm deployment:** the same `AGENT_REGISTRATION_TOKEN`
  environment variable on `switch-core`.
* **Switch Console–managed agent:** Console registers the agent with your
  signed-in session, so there is no token to mint. Skip to step 3 and read the
  agent id and API key from the agent's config in Console.

The token also decides ownership: the Gateway user it identifies becomes the
agent's owner, and an agent inherits exactly its owner's permissions.

---

## 2. Register the agent

```bash
curl -s -X POST "$BRIDGE_URL/agents/register-known" \
  -H "Authorization: Bearer $AGENT_REGISTRATION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "agent_type": "always_on",
        "name": "architect",
        "description": "ADR Architect",
        "options": {}
      }'
```

Response:

```json
{"id": "<agent id>", "api_key": "<agent api key>"}
```

Three things to get right:

1. **The API key is returned once.** Store it in the same step that receives
   it. This project keeps credentials in the environment, never in the repo.
2. **The returned `id` is what goes in every `/agents/{id}/...` URL.** Use it
   verbatim for `--agent-id`; do not assume it equals `name`.
3. **Names are a slug:** `^[a-z0-9][a-z0-9._-]*$`. Re-registering a name that
   already exists is a `409` unless you ask to overwrite — and an overwrite
   **rotates the key**, so anything still holding the old one stops working.

`agent_type` describes how the agent is actually run, and decides what other
participants expect from it. For this long-running client, `always_on` is
correct: it is reachable independently of any room, thanks to the heartbeat.

```bash
export SWITCH_AGENT_KEY="<api_key from the response>"
export SWITCH_AGENT_ID="<id from the response>"
```

---

## 3. Put the agent in the room, and let people address it

Registration does not make the agent a member of anything, and **a new agent
starts owner-only** for addressing. Two separate things have to be true before
it will answer a teammate:

* **Membership:** add the agent to the room. In Switch Console, open the agent
  and use **Add to room** (or invite it from the room's configuration page).
  The app must be in the underlying channel too, but that is the bridge's job.
* **Addressing policy:** in Console, on the agent's page, widen **who can talk
  to this agent** beyond the default. With no rules at all an agent is open;
  the moment a rule exists, everything it does not admit is denied.
* **Identity claims (only if teammates speak from Slack/Mattermost/Discord):**
  a platform account that is not claimed matches nobody — not even the owner —
  so the agent stays silent to that person. Link their messaging account to
  their Switch user first.

These three failures all look the same from chat: the agent is online and never
replies.

---

## 4. Find the room UUID

Ask the agent. `list_rooms` is an agent operation, so it returns the rooms
**the agent belongs to** — which is exactly the set you can connect to.

```bash
curl -s -X POST "$BRIDGE_URL/agents/$SWITCH_AGENT_ID/ops/list_rooms" \
  -H "Authorization: Bearer $SWITCH_AGENT_KEY" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Response (one entry per room):

```json
{
  "result": [
    {
      "room_id": "0f0c2f6e-6f1e-4b0a-9d63-2c1f0a7b9e11",
      "name": "Architecture & ADRs",
      "description": "Team room for architecture decisions",
      "connected": false,
      "archived": false
    }
  ]
}
```

Copy `room_id` — that is the room UUID. Notes:

* Pass `{"include_archived": true}` to include archived rooms.
* An empty list means the agent is not in any room yet: go back to step 3.
* `connected` reports whether this agent currently holds the room; `false` just
  means no live claim.
* The connection header (`X-Switch-Connection-Id`) is optional here because
  `list_rooms` is agent-scoped. Room-bound operations need it, and this client
  always sends it.

The room UUID is also available from the Gateway/dashboard if you prefer
clicking to curl, but the operation above is the value the agent itself will
use, so it is the one least likely to disagree with what you configured.

---

## 5. Run the agent against that room

```bash
python main.py \
  --bridge-url "$BRIDGE_URL" \
  --agent-id "$SWITCH_AGENT_ID" \
  --api-key "$SWITCH_AGENT_KEY" \
  --room "0f0c2f6e-6f1e-4b0a-9d63-2c1f0a7b9e11"
```

A room **name** also works — the client resolves it through `list_rooms` before
binding — but a UUID is unambiguous and survives a rename.

What the client does on startup, in order:

1. Opens the SSE stream: `GET /agents/{id}/events` with a client-generated
   `connection_id`, `scope=all`, `filter=all`. The connection id is reused
   across reconnects, so a dropped socket resumes from `Last-Event-ID`.
2. Starts the heartbeat: `POST /agents/{id}/connection/beat` every 2 seconds
   (TTL 6s). A `404` or `409` reopens the stream rather than backing off.
3. Claims the room with `connect_to_room`, which takes over the room and
   returns its instructions, participants and context.
4. Calls `post_message` / `read_context` with the connection id header and
   **unwrapped** argument objects. The room is implicit from the claim.

Run **one instance per agent id**. `connect_to_room` always takes over, and
reopening a live connection id is a takeover: two processes will evict each
other in a loop.

---

## 6. Confirm it works

In the room's channel:

```text
We need to pick a queue for order events.
I propose Kafka because of durable replay and partitioning.
The trade-off is broker operations overhead.
@architect summarize and draft an ADR.
```

Expected: a clarifying question in the thread, then — after a teammate answers
the rollback question — a MADR file under `docs/adr/` and a
`docs(adr): record ADR-xxxx` commit in the repository you started the agent in.

---

## Troubleshooting

| Symptom | Cause |
|:--|:--|
| `401` from `/agents/register-known` | You used an API key where a registration token is required |
| `409` from `/agents/register-known` | Name already registered; pick another name, or overwrite (which rotates the key and breaks the old one) |
| `403` on `connect_to_room` | The agent is not a member of that room |
| `404` on an operation | Wrong `--agent-id`; use the `id` returned at registration |
| Agent online, never answers | Owner-only addressing policy, an unclaimed platform account, or a message that never says `@architect` |
| Two agents fight / repeated evictions | Two processes using the same agent id or connection id; run one |
| Stream opens but no messages | The claim did not happen; check the `connect_to_room` line at startup. History is read with `read_context`, and events before the claim are not replayed |
| `room_id must be a UUID` style `400` | You passed a room name to a room-bound operation; pass the UUID from step 4 |

---

## Where this is implemented

| Concern | Code |
|:--|:--|
| Stream, heartbeat, cursor resume | `switch_client.py` (`_handle_sse_stream`, `_start_heartbeat`) |
| Operations, argument shape | `switch_client.py` (`_op`, `post_message`, `read_context`) |
| Room name → UUID resolution | `switch_client.py` (`list_rooms`, `resolve_room_id`) |
| Startup order | `main.py` (`client.start()`, then `connect_to_room`) |
| Contract enforcement in tests | `test_e2e.py` (`StrictSwitchHandler`, `TestSwitchProtocolContract`) |
