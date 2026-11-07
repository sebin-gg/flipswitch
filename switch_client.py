"""Switch agent client implementing the published Agent Protocol.

Transport: one SSE stream down (``GET /agents/{id}/events``), HTTP operations
up (``POST /agents/{id}/ops/{operation}``), plus a 2-second heartbeat on
``POST /agents/{id}/connection/beat``. Connection ids are client-generated and
reused across reconnects so a dropped socket resumes from its cursor.
"""

import json
import threading
import time
import uuid

import requests

UUID_RE = r"^[0-9a-fA-F-]{32,36}$"


class SwitchAgentClient:
    """Client implementing the Switch Agent wire protocol (SSE down, HTTP up)."""

    def __init__(
        self,
        bridge_url: str,
        agent_id: str = "architect",
        api_key: str = "switch-dev-key",
        agent_name: str = "Architect",
    ):
        self.bridge_url = bridge_url.rstrip("/")
        self.agent_id = agent_id
        self.api_key = api_key
        self.agent_name = agent_name
        self.connection_id = str(uuid.uuid4())
        self.connected_room_id = None
        self.cursor = 0
        self.running = False
        self.on_message_callback = None
        self._sse_session = None
        self._heartbeat_thread = None
        self._sse_thread = None

    # ------------------------------------------------------------------ auth
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "X-Switch-Connection-Id": self.connection_id,
            "Content-Type": "application/json",
        }

    def _op(self, name: str, args: dict = None):
        """Calls a Switch operation with unwrapped arguments, as the protocol requires."""
        url = f"{self.bridge_url}/agents/{self.agent_id}/ops/{name}"
        try:
            resp = requests.post(url, json=args or {}, headers=self._headers(), timeout=15)
            if resp.status_code != 200:
                return None
            data = resp.json()
            return data.get("result", data) if isinstance(data, dict) else data
        except Exception:
            return None

    # ------------------------------------------------------------- heartbeat
    def _start_heartbeat(self):
        """Heartbeat loop: POST /agents/{agent_id}/connection/beat every 2s."""

        def heartbeat_loop():
            while self.running:
                try:
                    url = f"{self.bridge_url}/agents/{self.agent_id}/connection/beat"
                    payload = {"connection_id": self.connection_id, "cursor": self.cursor}
                    resp = requests.post(url, json=payload, headers=self._headers(), timeout=5)
                    if resp.status_code in (404, 409):
                        # Protocol: both mean "reopen the stream", never "back off".
                        self._force_reconnect()
                except Exception:
                    pass
                time.sleep(2)

        self._heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    # ------------------------------------------------------------------- SSE
    def _force_reconnect(self):
        """Drops the current SSE socket; the read loop reopens with the same connection id."""
        session = self._sse_session
        if session is not None:
            try:
                session.close()
            except Exception:
                pass

    def _sse_url(self) -> str:
        return f"{self.bridge_url}/agents/{self.agent_id}/events"

    def _handle_sse_stream(self):
        """Maintains the SSE stream: GET /agents/{agent_id}/events."""
        params = {
            "connection_id": self.connection_id,
            "scope": "all",
            "filter": "all",
            "client": "switch-adr-architect",
            "client_version": "1.0.0",
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "text/event-stream",
        }
        if self.cursor:
            headers["Last-Event-ID"] = str(self.cursor)

        while self.running:
            self._sse_session = requests.Session()
            try:
                with self._sse_session.get(
                    self._sse_url(), headers=headers, params=params, stream=True, timeout=60
                ) as resp:
                    resp.raise_for_status()

                    current_event = None
                    current_data = []

                    # chunk_size=1 delivers each SSE frame immediately instead of
                    # waiting for the default 512-byte buffer to fill.
                    for raw_line in resp.iter_lines(chunk_size=1, decode_unicode=True):
                        if not self.running:
                            break
                        if raw_line is None:
                            continue
                        line = raw_line.strip()

                        if not line:
                            # Empty line dispatches the current SSE frame.
                            if current_event == "message" and current_data:
                                self._dispatch_message_event("\n".join(current_data))
                            current_event = None
                            current_data = []
                            continue

                        if line.startswith(":"):
                            continue  # keepalive comment
                        if line.startswith("event:"):
                            current_event = line.split("event:", 1)[1].strip()
                        elif line.startswith("id:"):
                            try:
                                self.cursor = int(line.split("id:", 1)[1].strip())
                                headers["Last-Event-ID"] = str(self.cursor)
                            except ValueError:
                                pass
                        elif line.startswith("data:"):
                            current_data.append(line.split("data:", 1)[1].strip())

            except Exception:
                if not self.running:
                    break
                time.sleep(2)

    def _dispatch_message_event(self, data_str: str):
        try:
            parsed = json.loads(data_str)
            room_id = parsed.get("room_id", "#general")
            payload = parsed.get("payload", {})
            if self.on_message_callback:
                self.on_message_callback(room_id, payload)
        except (json.JSONDecodeError, AttributeError):
            pass

    # ------------------------------------------------------------ operations
    def post_message(self, room_id: str = None, body: str = "", thread_id: str = None) -> dict:
        """POST ops/post_message. The room is implicit: use connect_to_room first."""
        args = {"body": body}
        if thread_id:
            args["thread_id"] = thread_id
        return self._op("post_message", args) or {}

    def read_context(self, room_id: str = None, limit: int = 50) -> list:
        """POST ops/read_context and flatten its threads into one timeline.

        The bridge returns {"threads": [{"root": entry, "replies": [...]}], ...}.
        The embedded simulator returns a flat list of messages.
        """
        import re

        args = {"limit": limit}
        # Only a real room UUID can be passed; the connection's room is implicit.
        if room_id and room_id != self.connected_room_id and re.match(UUID_RE, room_id):
            args["room_id"] = room_id
        result = self._op("read_context", args)
        if result is None:
            return []

        entries = []
        if isinstance(result, dict):
            if isinstance(result.get("threads"), list):
                for thread in result["threads"]:
                    if not isinstance(thread, dict):
                        continue
                    if thread.get("root"):
                        entries.append(thread["root"])
                    entries.extend(thread.get("replies") or [])
            elif isinstance(result.get("messages"), list):
                entries = result["messages"]
        elif isinstance(result, list):
            entries = result

        return [m for m in (self._normalize_message(item) for item in entries) if m]

    def list_rooms(self) -> list:
        result = self._op("list_rooms", {})
        if isinstance(result, dict):
            result = result.get("rooms", result.get("result", []))
        return result if isinstance(result, list) else []

    def resolve_room_id(self, room: str) -> str:
        """Accepts a Switch room UUID or a human room name and returns the UUID."""
        import re

        if not room or re.match(UUID_RE, room):
            return room
        for candidate in self.list_rooms():
            if not isinstance(candidate, dict):
                continue
            values = {str(candidate.get("id", "")), str(candidate.get("name", ""))}
            if room in values or room.lstrip("#").lower() in {v.lstrip("#").lower() for v in values}:
                return candidate.get("id", room)
        return room

    def connect_to_room(self, room_id: str) -> dict:
        resolved = self.resolve_room_id(room_id)
        result = self._op("connect_to_room", {"room_id": resolved}) or {}
        self.connected_room_id = resolved
        return result

    @staticmethod
    def _normalize_message(item: dict) -> dict:
        """Flattens bridge/simulator entry shapes into {sender, content}."""
        if not isinstance(item, dict):
            return {}
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        content = item.get("body") or payload.get("body") or item.get("content") or ""
        sender = (
            item.get("sender_name")
            or payload.get("sender_name")
            or item.get("sender")
            or "Teammate"
        )
        return {
            "sender": sender,
            "content": content,
            "message_id": item.get("id") or item.get("message_id"),
            "raw": item,
        }

    # ------------------------------------------------------------- lifecycle
    def start(self):
        if self.running:
            return
        self.running = True
        self._start_heartbeat()
        self._sse_thread = threading.Thread(target=self._handle_sse_stream, daemon=True)
        self._sse_thread.start()

    def stop(self):
        self.running = False
        if self._sse_session:
            try:
                self._sse_session.close()
            except Exception:
                pass
