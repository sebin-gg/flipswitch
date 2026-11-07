import os
import shutil
import stat
import subprocess
import threading
import time
import unittest
from pathlib import Path

from switch_simulator import create_server, send_room_message
from switch_client import SwitchAgentClient
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


if __name__ == "__main__":
    unittest.main()
