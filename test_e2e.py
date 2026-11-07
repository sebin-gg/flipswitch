import unittest
import threading
import time
import os
import shutil
import stat
from pathlib import Path

from switch_simulator import create_server, send_room_message
from switch_client import SwitchAgentClient
from agent_orchestrator import ADRArchitectAgent


def force_rmtree(path):
    def on_rm_error(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    if Path(path).exists():
        shutil.rmtree(path, onerror=on_rm_error)


class TestSwitchADRArchitect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = 8797
        cls.bridge_url = f"http://127.0.0.1:{cls.port}"
        cls.server = create_server(cls.port)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

        cls.test_dir = Path("D:/git/flipswitch/test_sandbox")
        force_rmtree(cls.test_dir)
        cls.test_dir.mkdir(parents=True, exist_ok=True)

        os.system(f'git -C "{cls.test_dir}" init')
        os.system(f'git -C "{cls.test_dir}" config user.name "Switch Bot"')
        os.system(f'git -C "{cls.test_dir}" config user.email "bot@switch.local"')

        cls.client = SwitchAgentClient(
            bridge_url=cls.bridge_url,
            agent_id="test-architect",
            api_key="test-key",
            agent_name="ADR Architect",
        )
        cls.orchestrator = ADRArchitectAgent(
            client=cls.client,
            repo_dir=str(cls.test_dir),
            adr_dir="docs/adr",
        )
        cls.client.start()
        time.sleep(1.0)

    @classmethod
    def tearDownClass(cls):
        cls.client.stop()
        force_rmtree(cls.test_dir)

    def test_01_health_and_connection(self):
        """Tests that Switch server health check succeeds."""
        import requests
        r = requests.get(f"{self.bridge_url}/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("service"), "switch-mock-bridge")

    def test_02_adr_generation_flow(self):
        """Simulates discussion, agent analysis, clarification, and git commit."""
        room = "#eng-architecture"

        # 1. Team discusses
        send_room_message(room, "DevA", "We need to choose between gRPC and REST for inter-service communication.")
        send_room_message(room, "DevB", "I propose we use gRPC because of protobuf performance, binary serialization, and generated types.")
        send_room_message(room, "DevC", "Trade-off is browser clients need grpc-web proxy and debugging binary payloads is harder.")
        time.sleep(0.5)

        # 2. Invoke architect
        send_room_message(room, "DevA", "@architect summarize our discussion and draft an ADR.", addressed=True)
        time.sleep(1.5)

        # 3. Answer question
        send_room_message(room, "DevB", "@architect Rollback plan is serving OpenAPI REST endpoints via grpc-gateway.", addressed=True)
        time.sleep(2.0)

        # Verify ADR file was written
        adr_files = list((self.test_dir / "docs/adr").glob("*.md"))
        self.assertTrue(len(adr_files) >= 1, "Expected ADR markdown file to be created")

        adr_doc = [f for f in adr_files if f.name != "README.md"][0]
        content = adr_doc.read_text(encoding="utf-8")
        self.assertIn("gRPC", content)
        self.assertIn("Rollback", content)

        # Verify README index was created
        readme_file = self.test_dir / "docs/adr/README.md"
        self.assertTrue(readme_file.exists())
        self.assertIn("ADR-0001", readme_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
