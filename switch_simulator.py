from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import queue
import time
import uuid
import sys

DEFAULT_PORT = 8765
SERVER_VERSION = "1.0.0"

# In-memory storage for room history and messages
rooms = {}
agent_connections = {}


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

    # Print chat event in terminal
    color_prefix = "\033[94m" if sender_name == "Architect" or "Architect" in sender_name else "\033[92m"
    print(f"{color_prefix}[{room_id}] {sender_name}:\033[0m {body}")

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
        elif "/stream" in clean_path:
            parts = clean_path.split("/")
            agent_id = parts[2] if len(parts) > 2 else "agent-default"
            self.handle_stream(agent_id)
        elif "/ops/read_context" in clean_path:
            parts = clean_path.split("/")
            agent_id = parts[2] if len(parts) > 2 else "agent-default"
            self.handle_read_context(agent_id)
        else:
            self.respond(404, {"error": "Not Found", "path": self.path})

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
            self.respond(200, {"result": {"connected": True}})
        else:
            self.respond(404, {"error": "Not Found", "path": self.path})

    def handle_heartbeat(self, agent_id):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            self.rfile.read(content_length)
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
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            if agent_id in agent_connections:
                del agent_connections[agent_id]

    def handle_post_message(self, agent_id):
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length)
        data = json.loads(body_bytes.decode("utf-8"))

        room_id = data.get("room_id", "#architecture")
        sender_name = data.get("sender_name", "ADR Architect")
        message_body = data.get("body", "")
        addressed = data.get("addressed", False)
        thread_id = data.get("thread_id")

        send_room_message(room_id, sender_name, message_body, addressed, thread_id)
        self.respond(200, {"result": {"message_id": str(uuid.uuid4())}})

    def handle_read_context(self, agent_id):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            self.rfile.read(content_length)
        all_messages = []
        for room_id in rooms.keys():
            all_messages.extend(rooms[room_id])
        self.respond(200, {"result": all_messages})

    def respond(self, status_code, data):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
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
    print(f"   SSE Stream:   http://localhost:{port}/agents/architect/stream")
    print(f"=======================================================\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Switch Simulator...")
        server.shutdown()


if __name__ == "__main__":
    p = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    run_server(p)
