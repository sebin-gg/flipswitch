import os
import re
import shutil
import stat
import subprocess
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from switch_simulator import SwitchHandler, create_server, send_room_message
from switch_client import UUID_RE, SwitchAgentClient
from agent_orchestrator import ADRArchitectAgent
from llm_engine import LLMClient, SmartADREngine


def force_rmtree(path):
    def on_rm_error(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    if Path(path).exists():
        shutil.rmtree(path, onerror=on_rm_error)


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class TestSwitchADRArchitect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ephemeral port so parallel runs never collide.
        cls.server = create_server(0)
        cls.port = cls.server.server_address[1]
        cls.bridge_url = f"http://127.0.0.1:{cls.port}"
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

        # Sandbox lives next to the tests and is covered by .gitignore.
        cls.test_dir = Path(__file__).resolve().parent / "test_sandbox"
        force_rmtree(cls.test_dir)
        cls.test_dir.mkdir(parents=True, exist_ok=True)

        git(cls.test_dir, "init")
        git(cls.test_dir, "config", "user.name", "Switch Bot")
        git(cls.test_dir, "config", "user.email", "bot@switch.local")

        cls.client = SwitchAgentClient(
            bridge_url=cls.bridge_url,
            agent_id="test-architect",
            api_key="test-key",
            agent_name="ADR Architect",
        )
        offline_llm = LLMClient(api_key="")
        offline_llm.api_key = None  # ignore any ambient API key in the test environment
        cls.engine = SmartADREngine(llm=offline_llm)
        cls.orchestrator = ADRArchitectAgent(
            client=cls.client,
            repo_dir=str(cls.test_dir),
            adr_dir="docs/adr",
            engine=cls.engine,
        )
        cls.client.start()
        time.sleep(1.0)
        cls.client.connect_to_room("#eng-architecture")

    @classmethod
    def tearDownClass(cls):
        cls.client.stop()
        cls.server.shutdown()
        cls.server.server_close()
        force_rmtree(cls.test_dir)

    def test_01_health_and_connection(self):
        """Switch server health check succeeds."""
        import requests

        r = requests.get(f"{self.bridge_url}/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("service"), "switch-mock-bridge")

    def test_02_adr_generation_flow(self):
        """Discussion -> agent analysis -> clarification -> git commit."""
        room = "#eng-architecture"

        # 1. Team discusses
        send_room_message(room, "DevA", "We need to choose between gRPC and REST for inter-service communication.")
        send_room_message(room, "DevB", "I propose we use gRPC because of protobuf performance, binary serialization, and generated types.")
        send_room_message(room, "DevC", "Trade-off is browser clients need grpc-web proxy and debugging binary payloads is harder.")
        time.sleep(0.5)

        # 2. Invoke architect
        send_room_message(room, "DevA", "@architect summarize our discussion and draft an ADR.", addressed=True)
        time.sleep(1.5)

        # 3. Answer the missing rollback question
        send_room_message(room, "DevB", "@architect Rollback plan is serving OpenAPI REST endpoints via grpc-gateway.", addressed=True)
        time.sleep(2.0)

        adr_files = [f for f in (self.test_dir / "docs/adr").glob("*.md") if f.name != "README.md"]
        self.assertTrue(len(adr_files) >= 1, "Expected ADR markdown file to be created")

        adr_doc = adr_files[0]
        content = adr_doc.read_text(encoding="utf-8")
        self.assertIn("gRPC", content)
        self.assertIn("Rollback", content)
        self.assertIn("grpc-gateway", content)

        # README index was created and lists the ADR
        readme_file = self.test_dir / "docs/adr/README.md"
        self.assertTrue(readme_file.exists())
        self.assertIn("ADR-0001", readme_file.read_text(encoding="utf-8"))

        # The decision was actually committed to git
        log = git(self.test_dir, "log", "--oneline").stdout
        self.assertIn("docs(adr)", log)

    def test_03_smart_engine_degrades_gracefully(self):
        """No API key => deterministic heuristic output, never a crash."""
        proposal = self.engine.analyze_discussion(
            [
                {"sender": "A", "content": "We need to pick a cache. I propose Redis because it is fast."},
                {"sender": "B", "content": "Trade-off is the operational overhead of another cluster."},
            ]
        )
        self.assertIn("Redis", proposal.decision)
        self.assertTrue(proposal.consequences_negative)

        # A configured but unreachable provider also falls back instead of raising.
        unreachable = SmartADREngine(
            llm=LLMClient(api_key="test-key", base_url="http://127.0.0.1:1", timeout=1)
        )
        fallback = unreachable.analyze_discussion(
            [{"sender": "A", "content": "I propose we use Redis for cache."}]
        )
        self.assertIn("Redis", fallback.decision)


class TestDuplicateADRGuard(unittest.TestCase):
    """Follow-up chatter must never re-record an already-finalized decision.

    Deterministic by construction: messages are handed to the orchestrator
    synchronously instead of being pushed through the SSE stream, so there are
    no sleeps or races around when the agent sees a message.
    """

    ROOM = "#dedupe-room"

    @classmethod
    def setUpClass(cls):
        cls.server = create_server(0)
        cls.port = cls.server.server_address[1]
        cls.bridge_url = f"http://127.0.0.1:{cls.port}"
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

        cls.test_dir = Path(__file__).resolve().parent / "test_sandbox_dedupe"
        force_rmtree(cls.test_dir)
        cls.test_dir.mkdir(parents=True, exist_ok=True)
        git(cls.test_dir, "init")
        git(cls.test_dir, "config", "user.name", "Switch Bot")
        git(cls.test_dir, "config", "user.email", "bot@switch.local")

        cls.client = SwitchAgentClient(
            bridge_url=cls.bridge_url,
            agent_id="dedupe-architect",
            api_key="test-key",
            agent_name="ADR Architect",
        )
        offline_llm = LLMClient(api_key="")
        offline_llm.api_key = None
        cls.orchestrator = ADRArchitectAgent(
            client=cls.client,
            repo_dir=str(cls.test_dir),
            adr_dir="docs/adr",
            engine=SmartADREngine(llm=offline_llm),
        )
        # No client.start(): the SSE stream stays closed so delivery order is ours.
        cls.client.connect_to_room(cls.ROOM)

    @classmethod
    def tearDownClass(cls):
        cls.client.stop()
        cls.server.shutdown()
        cls.server.server_close()
        force_rmtree(cls.test_dir)

    def _adr_files(self):
        return sorted((self.test_dir / "docs/adr").glob("00*.md"))

    def _commits(self):
        return int(git(self.test_dir, "rev-list", "--count", "HEAD").stdout.strip() or 0)

    def _say(self, body, sender="DevA", addressed=True):
        """Delivers one room message to the agent exactly as the bridge would."""
        self.orchestrator.handle_room_message(
            self.ROOM,
            {
                "sender_name": sender,
                "body": body,
                "addressed": addressed,
                "thread_id": self.ROOM,
            },
        )

    def _last_architect_reply(self):
        messages = self.client.read_context(self.ROOM, limit=50)
        for message in reversed(messages):
            if "architect" in str(message.get("sender", "")).lower():
                return message.get("content", "")
        return ""

    def test_follow_up_chatter_cannot_create_a_duplicate_adr(self):
        # 1. A real decision is discussed (plain chatter is not addressed to the agent)
        # and then recorded after one clarification round.
        self._say("We need a cache for session data.", addressed=False)
        self._say("I propose Redis because it is fast and mature.", addressed=False)
        self._say("@architect draft an ADR for this.")
        self.assertIn(self.ROOM, self.orchestrator.active_state)
        self.assertEqual(self._adr_files(), [])

        self._say("@architect Rollback plan is reverting to the database session store.")
        files_after_record = self._adr_files()
        self.assertEqual(len(files_after_record), 1, "the first decision should be recorded")
        commits_after_record = self._commits()
        self.assertEqual(commits_after_record, 1)

        # 2. The paragraph that used to produce a second ADR.
        self._say(
            "@architect Thanks, that looks good. Also add that the team liked the "
            "simple operational story and that we will revisit next quarter."
        )

        self.assertEqual(
            self._adr_files(),
            files_after_record,
            "follow-up chatter created a duplicate ADR file",
        )
        self.assertEqual(self._commits(), commits_after_record, "duplicate commit was created")
        reply = self._last_architect_reply()
        self.assertIn("already recorded", reply.lower())
        self.assertIn(files_after_record[0].name, reply)

        # Even several more follow-ups in a row stay quiet.
        for text in (
            "@architect Should we also mention the eviction policy?",
            "@architect One more note for the record: costs were acceptable.",
        ):
            self._say(text)
        self.assertEqual(len(self._adr_files()), 1)
        self.assertEqual(self._commits(), commits_after_record)

        # 3. The documented escape hatch still works: an explicit new topic.
        self._say(
            "@architect new ADR: adopt Postgres for persistence. Rollback plan is a "
            "pg_dump restore. Trade-off is the operational overhead of a managed "
            "database. Benefit is faster queries with real indexes."
        )
        self.assertEqual(
            len(self._adr_files()),
            2,
            "an explicit 'new ADR' request should still record a new decision",
        )


class StrictSwitchHandler(SwitchHandler):
    """Simulator handler that rejects anything outside the published protocol.

    The permissive mock accepts unknown arguments silently, which hides client
    drift. This gate fails loudly on unknown operation arguments, a missing
    connection header, a wrong stream path, or a non-UUID ``room_id``.
    """

    violations = []
    requests = []
    lock = threading.Lock()

    ALLOWED_ARGS = {
        "post_message": {"body", "thread_id"},
        "read_context": {"limit", "room_id", "since", "before"},
        "connect_to_room": {"room_id"},
        "list_rooms": set(),
    }

    @classmethod
    def reset(cls):
        with cls.lock:
            cls.violations.clear()
            cls.requests.clear()

    def _record(self, method):
        parsed = urlparse(self.path)
        with self.lock:
            self.requests.append(
                {
                    "method": method,
                    "path": parsed.path,
                    "query": parse_qs(parsed.query),
                    "has_connection_header": bool(
                        self.headers.get("X-Switch-Connection-Id")
                    ),
                    "accept": self.headers.get("Accept", ""),
                }
            )

    def _violate(self, reason):
        with self.lock:
            self.violations.append(reason)
        self.respond(400, {"error": reason})

    def read_json_body(self):
        # Cache so validation and the inherited handler share one body read.
        if "_cached_body" not in self.__dict__:
            self._cached_body = super().read_json_body()
        return self._cached_body

    def do_GET(self):
        self._record("GET")
        path = urlparse(self.path).path
        if path == "/health":
            return super().do_GET()
        if not re.match(r"^/agents/[^/]+/events$", path):
            return self._violate(f"unexpected GET {path} (expected /agents/{{id}}/events)")

        query = parse_qs(urlparse(self.path).query)
        if not query.get("connection_id"):
            return self._violate("events stream missing connection_id")
        if (query.get("scope") or [None])[0] not in ("all", "single"):
            return self._violate("events stream missing scope")
        if (query.get("filter") or [None])[0] not in ("all", "addressed"):
            return self._violate("events stream missing filter")
        return super().do_GET()

    def do_POST(self):
        self.__dict__.pop("_cached_body", None)
        self._record("POST")
        path = urlparse(self.path).path

        if not self.headers.get("X-Switch-Connection-Id"):
            return self._violate(f"missing X-Switch-Connection-Id on {path}")

        if path.endswith("/connection/beat"):
            body = self.read_json_body()
            extra = set(body) - {"connection_id", "cursor"}
            if extra:
                return self._violate(f"heartbeat got unexpected args {sorted(extra)}")
            if not body.get("connection_id"):
                return self._violate("heartbeat missing connection_id")
            return super().do_POST()

        parts = path.split("/")
        if len(parts) < 5 or parts[3] != "ops":
            return self._violate(f"unexpected POST {path}")
        op = parts[4]
        if op not in self.ALLOWED_ARGS:
            return self._violate(f"unknown operation {op}")

        body = self.read_json_body()
        extra = set(body) - self.ALLOWED_ARGS[op]
        if extra:
            return self._violate(f"{op} got unexpected args {sorted(extra)}")
        if op == "connect_to_room" and not body.get("room_id"):
            return self._violate("connect_to_room requires room_id")
        if op == "read_context" and body.get("room_id"):
            if not re.match(UUID_RE, str(body["room_id"])):
                return self._violate("read_context room_id must be a room UUID")
        return super().do_POST()


def create_strict_server(port=0):
    server = ThreadingHTTPServer(("127.0.0.1", port), StrictSwitchHandler)
    server.daemon_threads = True
    return server


class TestSwitchProtocolContract(unittest.TestCase):
    """Runs the real client against a bridge that rejects protocol drift."""

    @classmethod
    def setUpClass(cls):
        StrictSwitchHandler.reset()
        cls.server = create_strict_server(0)
        cls.port = cls.server.server_address[1]
        cls.bridge_url = f"http://127.0.0.1:{cls.port}"
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

        cls.test_dir = Path(__file__).resolve().parent / "test_sandbox_contract"
        force_rmtree(cls.test_dir)
        cls.test_dir.mkdir(parents=True, exist_ok=True)
        git(cls.test_dir, "init")
        git(cls.test_dir, "config", "user.name", "Switch Bot")
        git(cls.test_dir, "config", "user.email", "bot@switch.local")

        cls.client = SwitchAgentClient(
            bridge_url=cls.bridge_url,
            agent_id="contract-architect",
            api_key="test-key",
            agent_name="ADR Architect",
        )
        offline_llm = LLMClient(api_key="")
        offline_llm.api_key = None
        cls.orchestrator = ADRArchitectAgent(
            client=cls.client,
            repo_dir=str(cls.test_dir),
            adr_dir="docs/adr",
            engine=SmartADREngine(llm=offline_llm),
        )
        cls.client.start()
        time.sleep(1.0)
        cls.client.connect_to_room("#contract-room")

    @classmethod
    def tearDownClass(cls):
        cls.client.stop()
        cls.server.shutdown()
        cls.server.server_close()
        force_rmtree(cls.test_dir)

    def test_01_gate_rejects_unexpected_arguments(self):
        """Positive control: the strict gate is not vacuous."""
        import requests

        # Connection setup (stream open, room bind, heartbeat) must already be clean.
        self.assertEqual(
            StrictSwitchHandler.violations,
            [],
            f"setup drifted from the protocol: {StrictSwitchHandler.violations}",
        )
        # The historical bug: post_message carried a room_id the real bridge rejects.
        r = requests.post(
            f"{self.bridge_url}/agents/contract-architect/ops/post_message",
            json={"body": "hi", "room_id": "#contract-room"},
            headers={
                "X-Switch-Connection-Id": self.client.connection_id,
                "Authorization": "Bearer test-key",
            },
            timeout=5,
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("unexpected args", r.json().get("error", ""))
        self.assertTrue(
            any("room_id" in v for v in StrictSwitchHandler.violations),
            f"gate failed to record a violation: {StrictSwitchHandler.violations}",
        )

        # A rejected op must surface as a client failure, never a silent success.
        self.assertIsNone(
            self.client._op("post_message", {"body": "hi", "room_id": "#contract-room"})
        )
        # Clear only the violations; the request log stays for the flow test.
        with StrictSwitchHandler.lock:
            StrictSwitchHandler.violations.clear()

    def test_02_flow_uses_events_and_clean_args(self):
        """Full ADR flow completes with zero protocol violations."""
        with StrictSwitchHandler.lock:
            StrictSwitchHandler.violations.clear()
        room = "#contract-room"

        send_room_message(room, "DevA", "We need to pick a queue for order events.")
        send_room_message(room, "DevB", "I propose Kafka because of durable replay and partitioning.")
        time.sleep(0.5)
        send_room_message(
            room,
            "DevA",
            "@architect summarize this and draft an ADR.",
            addressed=True,
        )
        time.sleep(1.5)
        send_room_message(
            room,
            "DevB",
            "@architect Rollback plan is dual-writing to RabbitMQ during migration.",
            addressed=True,
        )
        time.sleep(2.0)

        self.assertEqual(
            StrictSwitchHandler.violations,
            [],
            f"client drifted from the protocol: {StrictSwitchHandler.violations}",
        )

        with StrictSwitchHandler.lock:
            requests_seen = list(StrictSwitchHandler.requests)
        paths = [r["path"] for r in requests_seen]

        # The stream is opened on /events, never the non-existent /stream alias.
        event_requests = [r for r in requests_seen if r["path"].endswith("/events")]
        self.assertTrue(event_requests, f"client never opened /events; saw {paths}")
        self.assertFalse(
            any("/stream" in p for p in paths),
            f"client used a non-protocol stream path: {paths}",
        )
        for req in event_requests:
            self.assertEqual(req["method"], "GET")
            self.assertIn("text/event-stream", req["accept"])
            self.assertIn("connection_id", req["query"])
            self.assertIn("scope", req["query"])
            self.assertIn("filter", req["query"])

        # Every operation was sent with the connection header and unwrapped args.
        op_requests = [r for r in requests_seen if "/ops/" in r["path"]]
        self.assertTrue(op_requests, "no operations were sent")
        self.assertTrue(all(r["has_connection_header"] for r in op_requests))
        for expected_op in ("post_message", "read_context", "connect_to_room"):
            self.assertTrue(
                any(r["path"].endswith(f"/ops/{expected_op}") for r in op_requests),
                f"expected operation {expected_op} was never called",
            )

        # And the work actually happened: an ADR file exists and is committed.
        adr_files = [f for f in (self.test_dir / "docs/adr").glob("*.md") if f.name != "README.md"]
        self.assertTrue(adr_files, "expected an ADR to be written through the strict bridge")
        self.assertIn("docs(adr)", git(self.test_dir, "log", "--oneline").stdout)


if __name__ == "__main__":
    unittest.main()
