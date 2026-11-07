#!/usr/bin/env python3
"""Switch ADR Architect Agent — Multiplayer Architecture Decision Records in Team Chat.

Flip the Switch Hackathon (WeMakeDevs x DevTools Academy).

Modes:
    python main.py --simulate      Embedded Switch Bridge + scripted team demo
    python main.py --interactive   Embedded bridge, chat with the agent yourself
    python main.py                 Connect to a live Switch instance and listen
"""

import argparse
import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from switch_client import SwitchAgentClient
from agent_orchestrator import ADRArchitectAgent
from llm_engine import SmartADREngine
from switch_simulator import create_server, send_room_message

# Agent replies contain emoji; make sure a cp1252 Windows console never breaks them.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def run_demo_conversation(room_id: str, repo_dir: str) -> bool:
    """Simulates a realistic team chat interaction over Switch. Returns True on success."""
    adr_dir = Path(repo_dir) / "docs" / "adr"
    before = {f.name for f in adr_dir.glob("*.md")} if adr_dir.exists() else set()

    time.sleep(1.0)
    print("\n\033[1;36m=== [DEMO SIMULATION] Team starts architecture discussion in chat ===\033[0m\n")

    send_room_message(
        room_id,
        "Alice",
        "Team, we need to decide on our primary database for the telemetry and metrics pipeline.",
    )
    time.sleep(1.0)
    send_room_message(
        room_id,
        "Bob",
        "I propose we choose PostgreSQL with TimescaleDB because it is mature and supports fast SQL queries.",
    )
    time.sleep(1.0)
    send_room_message(
        room_id,
        "Charlie",
        "The trade-off is that we will need dedicated vacuum tuning and partition management overhead.",
    )
    time.sleep(1.0)
    send_room_message(
        room_id,
        "Alice",
        "Alternative was ClickHouse, but team has zero ClickHouse operations experience.",
    )
    time.sleep(1.5)

    print("\n\033[1;36m=== [DEMO SIMULATION] Lead invokes ADR Architect agent in room ===\033[0m\n")
    send_room_message(
        room_id,
        "Alice",
        "@architect summarize our discussion and draft an ADR.",
        addressed=True,
    )

    time.sleep(3.0)

    print("\n\033[1;36m=== [DEMO SIMULATION] Engineer provides missing rollback strategy in chat ===\033[0m\n")
    send_room_message(
        room_id,
        "Bob",
        "@architect In case of failure, our rollback strategy is falling back to managed Aurora read-replicas.",
        addressed=True,
    )

    time.sleep(4.0)
    print("\n\033[1;32m=== [DEMO SIMULATION COMPLETED] Verifying generated Git repository assets ===\033[0m\n")

    after = {f.name for f in adr_dir.glob("*.md")} if adr_dir.exists() else set()
    new_files = sorted(after - before)

    if new_files:
        for name in new_files:
            path = adr_dir / name
            print(f"\n--- Preview: {name} ---")
            print(path.read_text(encoding="utf-8")[:500] + "\n...")
    else:
        print("❌ No new ADR was generated. Check the agent output above.")
        return False

    print("\nRecent git commits:")
    os.system(f'git -C "{repo_dir}" log -n 2 --oneline')
    print("\n✅ Demo complete: ADR written and committed.")
    return True


def build_engine(args) -> SmartADREngine:
    """Builds the smart engine, honouring --no-llm and --model overrides."""
    if args.no_llm:
        engine = SmartADREngine()
        engine.llm.api_key = None
        return engine

    from llm_engine import LLMClient

    llm = LLMClient(model=args.model, base_url=args.llm_base_url)
    return SmartADREngine(llm=llm)


def main():
    parser = argparse.ArgumentParser(description="Switch ADR Architect Agent")
    parser.add_argument("--bridge-url", default="http://127.0.0.1:8765", help="Switch Agent Bridge URL")
    parser.add_argument("--agent-id", default="architect", help="Switch Agent ID")
    parser.add_argument("--api-key", default="switch-dev-key", help="Switch API Key")
    parser.add_argument("--room", default="#architecture-review", help="Chat room to join")
    parser.add_argument("--simulate", action="store_true", help="Run with embedded Switch Bridge simulator & live demo")
    parser.add_argument("--interactive", action="store_true", help="Launch interactive chat prompt with the agent")
    parser.add_argument("--embedded", action="store_true", help="Run the embedded bridge without a scripted demo")
    parser.add_argument("--model", default=None, help="Smart-model name (default: $ADR_MODEL or gpt-4.1)")
    parser.add_argument("--llm-base-url", default=None, help="OpenAI-compatible base URL for the smart model")
    parser.add_argument("--no-llm", action="store_true", help="Force the offline heuristic ADR engine")
    parser.add_argument("--list-models", action="store_true", help="Print the active ADR engine and exit")

    args = parser.parse_args()
    repo_dir = os.path.dirname(os.path.abspath(__file__))

    engine = build_engine(args)
    if args.list_models:
        print(f"🧠 ADR engine: {engine.describe()}")
        return

    use_embedded = args.simulate or args.interactive or args.embedded
    simulator_server = None
    if use_embedded:
        port = urlparse(args.bridge_url).port or 8765
        try:
            simulator_server = create_server(port)
        except OSError as exc:
            print(f"❌ Could not start embedded Switch Bridge on port {port}: {exc}")
            print("   Is the port already in use? Pass --bridge-url http://127.0.0.1:<free-port>.")
            sys.exit(1)
        sim_thread = threading.Thread(target=simulator_server.serve_forever, daemon=True)
        sim_thread.start()
        print(f"📡 Embedded Switch Bridge started on http://127.0.0.1:{port}")

    # Initialize Switch Agent Client
    client = SwitchAgentClient(
        bridge_url=args.bridge_url,
        agent_id=args.agent_id,
        api_key=args.api_key,
        agent_name="ADR Architect",
    )

    # Initialize Orchestrator with the smart (LLM-backed) engine
    orchestrator = ADRArchitectAgent(client=client, repo_dir=repo_dir, adr_dir="docs/adr", engine=engine)

    # Connect to room and start SSE stream
    client.start()
    client.connect_to_room(args.room)
    print(f"🤖 ADR Architect Agent connected to Switch ({args.bridge_url}) and listening in {args.room}")
    print(f"🧠 ADR engine: {engine.describe()}\n")

    if args.simulate:
        ok = run_demo_conversation(args.room, repo_dir)
        client.stop()
        if simulator_server:
            simulator_server.shutdown()
        sys.exit(0 if ok else 1)

    if args.interactive:
        print("\033[1;33m💬 Interactive Switch Chat Mode. Type messages as a human teammate.\033[0m")
        print("   Example: 'We should use Redis for session cache because it is fast.'")
        print("   Example: '@architect draft ADR for session cache'  (type 'exit' to quit)\n")
        try:
            while True:
                msg = input(f"[{args.room}] You: ")
                if not msg.strip():
                    continue
                if msg.lower() in ["exit", "quit"]:
                    break
                send_room_message(args.room, "You", msg, addressed="@architect" in msg.lower())
                time.sleep(1.0)
        except (KeyboardInterrupt, EOFError):
            pass
        client.stop()
        if simulator_server:
            simulator_server.shutdown()
        sys.exit(0)

    # Normal daemon run mode
    print("Agent running in background. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping ADR Architect Agent...")
    finally:
        client.stop()
        if simulator_server:
            simulator_server.shutdown()


if __name__ == "__main__":
    main()
