from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import json
import threading
import queue
import time
import uuid
import sys

DEFAULT_PORT = 8765
SERVER_VERSION = "1.0.0"

# Emoji-rich agent replies must not crash a cp1252 Windows console.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# In-memory storage for room history and messages
rooms = {}
agent_connections = {}
agent_rooms = {}


class StreamEvent:
    def __init__(self, event_type, data, id=None):
        self.id = id or str(uuid.uuid4())
        self.event_type = event_type
        self.data = data

    def encode(self):
        msg = ""
        if self.id:
            msg += f"id: {self.id}\n"
        if self.event_type:
            msg += f"event: {self.event_type}\n"
        msg += f"data: {json.dumps(self.data)}\n\n"
        return msg


def send_room_message(room_id, sender_name, body, addressed=False, thread_id=None):
    """Sends a message to a room, recording it and pushing the event to connected agents."""
    if room_id not in rooms:
        rooms[room_id] = []

    sequence = len(rooms[room_id]) + 1
    message = {
        "type": "message",
        "room_id": room_id,
        "payload": {
            "addressed": addressed,
            "sender_name": sender_name,
            "body": body,
            "thread_id": thread_id or room_id,
        },
        "sequence": sequence,
    }
    rooms[room_id].append(message)

    # Print chat event in terminal (never let an encoding quirk kill the stream)
    color_prefix = "\033[94m" if "architect" in str(sender_name).lower() else "\033[92m"
    line = f"{color_prefix}[{room_id}] {sender_name}:\033[0m {body}"
    try:
        print(line)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(encoding, "replace").decode(encoding, "replace"))

    event = StreamEvent("message", message, id=str(sequence))
    for conn in list(agent_connections.values()):
        conn["queue"].put(event)


class SwitchHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Silence routine request logging
        pass

    def do_GET(self):
        clean_path = self.path.split("?")[0]
        if clean_path == "/health":
            self.respond(200, {"status": "healthy", "service": "switch-mock-bridge", "version": SERVER_VERSION})
        elif "/events" in clean_path or "/stream" in clean_path:
            parts = clean_path.split("/")
            agent_id = parts[2] if len(parts) > 2 else "agent-default"
            self.handle_stream(agent_id)
        elif "/ops/read_context" in clean_path:
            parts = clean_path.split("/")
            agent_id = parts[2] if len(parts) > 2 else "agent-default"
            self.handle_read_context(agent_id)
        else:
            self.respond(404, {"error": "Not Found"})

    def do_POST(self):
        clean_path = self.path.split("?")[0]
        if "/connection/beat" in clean_path:
            parts = clean_path.split("/")
            agent_id = parts[2] if len(parts) > 2 else "agent-default"
            self.handle_heartbeat(agent_id)
        elif "/ops/post_message" in clean_path:
            parts = clean_path.split("/")
            agent_id = parts[2] if len(parts) > 2 else "agent-default"
            self.handle_post_message(agent_id)
        elif "/ops/read_context" in clean_path:
            parts = clean_path.split("/")
            agent_id = parts[2] if len(parts) > 2 else "agent-default"
            self.handle_read_context(agent_id)
        elif "/ops/connect_to_room" in clean_path:
            parts = clean_path.split("/")
            agent_id = parts[2] if len(parts) > 2 else "agent-default"
            self.handle_connect_to_room(agent_id)
        elif "/ops/list_rooms" in clean_path:
            self.respond(200, {"result": [{"id": r, "name": r} for r in rooms.keys()]})
        else:
            self.respond(404, {"error": "Not Found"})

    def handle_heartbeat(self, agent_id):
        # read_json_body (not a raw rfile read) so subclasses can inspect the
        # payload first and still let the request complete exactly once.
        self.read_json_body()
        self.respond(200, {"ok": True, "rooms": list(rooms.keys()), "cursor": 100})

    def handle_stream(self, agent_id):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        # Initial connection_state frame as per Switch Protocol
        connection_state = StreamEvent(
            "connection_state",
            {
                "status": "connected",
                "agent_id": agent_id,
                "protocol": 6,
                "rooms": list(rooms.keys()),
                "heartbeat_interval_seconds": 2,
            },
        )
        self.wfile.write(connection_state.encode().encode("utf-8"))
        self.wfile.flush()

        q = queue.Queue()
        agent_connections[agent_id] = {"queue": q}
        try:
            while True:
                try:
                    event = q.get(timeout=1.0)
                    self.wfile.write(event.encode().encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    # Keepalive comment
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except Exception as e:
            print(f"SSE stream exception for {agent_id}: {type(e)} {e}")
        finally:
            if agent_id in agent_connections:
                del agent_connections[agent_id]

    def handle_connect_to_room(self, agent_id):
        data = self.read_json_body()
        room_id = data.get("room_id")
        if not room_id:
            self.respond(400, {"error": "room_id is required"})
            return
        agent_rooms[agent_id] = room_id
        rooms.setdefault(room_id, [])
        self.respond(
            200,
            {
                "result": {
                    "agent_id": agent_id,
                    "room_id": room_id,
                    "name": room_id,
                    "participants": [],
                    "instructions": "Mock Switch room created by the embedded simulator.",
                }
            },
        )

    def handle_post_message(self, agent_id):
        data = self.read_json_body()
        # The real protocol has no room_id argument: the connection's room is used.
        room_id = agent_rooms.get(agent_id, "#architecture-review")
        message_body = data.get("body", "")
        thread_id = data.get("thread_id")

        send_room_message(room_id, "ADR Architect", message_body, False, thread_id)
        self.respond(200, {"result": {"event_id": str(uuid.uuid4())}})

    def handle_read_context(self, agent_id):
        data = self.read_json_body()
        query = parse_qs(urlparse(self.path).query)
        room_id = data.get("room_id") or (query.get("room_id") or [None])[0]
        try:
            limit = int(data.get("limit") or (query.get("limit") or [50])[0])
        except (TypeError, ValueError):
            limit = 50

        if not room_id:
            room_id = agent_rooms.get(agent_id)
        if room_id:
            messages = list(rooms.get(str(room_id), []))
        else:
            messages = [m for history in rooms.values() for m in history]
        self.respond(200, {"result": messages[-limit:]})

    def read_json_body(self):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            return {}
        raw = self.rfile.read(content_length)
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def respond(self, status_code, data):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        # Never let a browser treat an API payload as markup: exact JSON type,
        # and no MIME sniffing.
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)


def create_server(port=DEFAULT_PORT):
    server = ThreadingHTTPServer(("", port), SwitchHandler)
    server.daemon_threads = True
    return server


def run_server(port=DEFAULT_PORT):
    server = create_server(port)
    print(f"\n=======================================================")
    print(f"🚀 Switch Mock Bridge Server listening on port {port}")
    print(f"   Health check: http://localhost:{port}/health")
    print(f"   SSE Stream:   http://localhost:{port}/agents/architect/events")
    print(f"=======================================================\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Switch Simulator...")
        server.shutdown()


if __name__ == "__main__":
    p = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    run_server(p)
