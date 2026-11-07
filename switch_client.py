import time
import uuid
import json
import threading
from urllib.parse import urlencode
import requests
from requests.exceptions import RequestException


class SwitchAgentClient:
    """Client implementing the Switch Agent wire protocol (SSE down, HTTP up)."""

    def __init__(self, bridge_url: str, agent_id: str = "architect", api_key: str = "switch-dev-key", agent_name: str = "Architect"):
        self.bridge_url = bridge_url.rstrip("/")
        self.agent_id = agent_id
        self.api_key = api_key
        self.agent_name = agent_name
        self.connection_id = str(uuid.uuid4())
        self.cursor = 0
        self.running = False
        self.on_message_callback = None
        self._sse_session = None
        self._heartbeat_thread = None
        self._sse_thread = None

    def _start_heartbeat(self):
        """Heartbeat loop: POST /agents/{agent_id}/connection/beat every 2s."""
        def heartbeat_loop():
            while self.running:
                try:
                    url = f"{self.bridge_url}/agents/{self.agent_id}/connection/beat"
                    payload = {"connection_id": self.connection_id, "cursor": self.cursor}
                    headers = {
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    }
                    requests.post(url, json=payload, headers=headers, timeout=5)
                except Exception as e:
                    pass
                time.sleep(2)

        self._heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _handle_sse_stream(self):
        """Maintains SSE stream: GET /agents/{agent_id}/stream."""
        url = f"{self.bridge_url}/agents/{self.agent_id}/stream"
        params = {"connection_id": self.connection_id, "scope": "all"}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "text/event-stream"
        }

        while self.running:
            self._sse_session = requests.Session()
            try:
                with self._sse_session.get(url, headers=headers, params=params, stream=True, timeout=60) as resp:
                    resp.raise_for_status()

                    current_event = None
                    current_data = []

                    for raw_line in resp.iter_lines(decode_unicode=True):
                        if not self.running:
                            break
                        if raw_line is None:
                            continue
                        line = raw_line.strip()

                        if not line:
                            # Empty line signals dispatch of current SSE frame
                            if current_event == "message" and current_data:
                                full_data = "\n".join(current_data)
                                self._dispatch_message_event(full_data)
                            current_event = None
                            current_data = []
                            continue

                        if line.startswith(":"):
                            # Comment / keepalive
                            continue
                        elif line.startswith("event:"):
                            current_event = line.split("event:", 1)[1].strip()
                        elif line.startswith("id:"):
                            try:
                                self.cursor = int(line.split("id:", 1)[1].strip())
                            except ValueError:
                                pass
                        elif line.startswith("data:"):
                            current_data.append(line.split("data:", 1)[1].strip())

            except Exception as e:
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
        except json.JSONDecodeError as err:
            pass

    def post_message(self, room_id: str, body: str, thread_id: str = None) -> dict:
        """Invokes POST /agents/{agent_id}/ops/post_message."""
        url = f"{self.bridge_url}/agents/{self.agent_id}/ops/post_message"
        payload = {
            "room_id": room_id,
            "body": body,
            "sender_name": self.agent_name,
            "thread_id": thread_id
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Switch-Connection-Id": self.connection_id,
            "Content-Type": "application/json"
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            return resp.json() if resp.status_code == 200 else {}
        except Exception:
            return {}

    def read_context(self, room_id: str, limit: int = 50) -> list:
        """Invokes POST or GET /agents/{agent_id}/ops/read_context."""
        url = f"{self.bridge_url}/agents/{self.agent_id}/ops/read_context"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Switch-Connection-Id": self.connection_id,
            "Content-Type": "application/json"
        }
        payload = {"room_id": room_id, "limit": limit}
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code != 200:
                resp = requests.get(url, params=payload, headers=headers, timeout=10)
            data = resp.json()
            if isinstance(data, dict) and "result" in data:
                return data["result"]
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def connect_to_room(self, room_id: str) -> dict:
        url = f"{self.bridge_url}/agents/{self.agent_id}/ops/connect_to_room"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Switch-Connection-Id": self.connection_id,
            "Content-Type": "application/json"
        }
        try:
            resp = requests.post(url, json={"room_id": room_id}, headers=headers, timeout=10)
            return resp.json() if resp.status_code == 200 else {}
        except Exception:
            return {}

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
