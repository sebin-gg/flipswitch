#!/usr/bin/env python3
"""Switch ADR Architect Agent — Multiplayer Architecture Decision Records in Team Chat.

Flip the Switch Hackathon (WeMakeDevs x DevTools Academy).
"""

import argparse
import os
import sys
import time
import threading

from switch_client import SwitchAgentClient
from agent_orchestrator import ADRArchitectAgent
from switch_simulator import create_server, send_room_message


def run_demo_conversation(room_id: str):
    """Simulates realistic team chat interaction over Switch."""
    time.sleep(1.5)
    print("\n\033[1;36m=== [DEMO SIMULATION] Team starts architecture discussion in chat ===\033[0m\n")

    send_room_message(
        room_id,
        "Alice",
        "Team, we need to decide on our primary database for the telemetry and metrics pipeline.",
    )
    time.sleep(1.2)
    send_room_message(
        room_id,
        "Bob",
        "I propose we choose PostgreSQL with TimescaleDB because it is mature and supports fast SQL queries.",
    )
    time.sleep(1.2)
    send_room_message(
        room_id,
        "Charlie",
        "The trade-off is that we will need dedicated vacuum tuning and partition management overhead.",
    )
    time.sleep(1.2)
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

    time.sleep(2.5)

    print("\n\033[1;36m=== [DEMO SIMULATION] Engineer provides missing rollback strategy in chat ===\033[0m\n")
    send_room_message(
        room_id,
        "Bob",
        "@architect In case of failure, our rollback strategy is falling back to managed Aurora read-replicas.",
        addressed=True,
    )

    time.sleep(2.5)

    print("\n\033[1;32m=== [DEMO SIMULATION COMPLETED] Checking generated git repository assets ===\033[0m\n")
    os.system("git status")


def main():
    parser = argparse.ArgumentParser(description="Switch ADR Architect Agent")
    parser.add_argument("--bridge-url", default="http://localhost:8765", help="Switch Agent Bridge URL")
    parser.add_argument("--agent-id", default="architect", help="Switch Agent ID")
    parser.add_argument("--api-key", default="switch-dev-key", help="Switch API Key")
    parser.add_argument("--room", default="#architecture-review", help="Chat room to join")
    parser.add_argument("--simulate", action="store_true", help="Run with embedded Switch Bridge simulator & live demo")
    parser.add_argument("--interactive", action="store_true", help="Launch interactive chat prompt with the agent")

    args = parser.parse_args()

    simulator_server = None
    if args.simulate or args.bridge_url == "http://localhost:8765":
        # Launch lightweight Switch Bridge server
        port = int(args.bridge_url.split(":")[-1].replace("/", ""))
        simulator_server = create_server(port)
        sim_thread = threading.Thread(target=simulator_server.serve_forever, daemon=True)
        sim_thread.start()
        print(f"📡 Embedded Switch Bridge started on {args.bridge_url}")

    # Initialize Switch Agent Client
    client = SwitchAgentClient(
        bridge_url=args.bridge_url,
        agent_id=args.agent_id,
        api_key=args.api_key,
        agent_name="ADR Architect",
    )

    # Initialize Orchestrator
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    orchestrator = ADRArchitectAgent(client=client, repo_dir=repo_dir, adr_dir="docs/adr")

    # Connect to room and start SSE stream
    client.start()
    client.connect_to_room(args.room)
    print(f"🤖 ADR Architect Agent connected to Switch ({args.bridge_url}) and listening in {args.room}")

    if args.simulate:
        run_demo_conversation(args.room)
        client.stop()
        if simulator_server:
            simulator_server.shutdown()
        return

    if args.interactive:
        print("\n\033[1;33m💬 Interactive Switch Chat Mode. Type messages as a human teammate.\033[0m")
        print("   Example: 'We should use Redis for session cache because it is fast.'")
        print("   Example: '@architect draft ADR for session cache'\n")
        try:
            while True:
                msg = input(f"[{args.room}] You: ")
                if not msg.strip():
                    continue
                if msg.lower() in ["exit", "quit"]:
                    break
                send_room_message(args.room, "You", msg, addressed="@architect" in msg.lower())
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass
        finally:
            client.stop()
            if simulator_server:
                simulator_server.shutdown()
            return

    # Normal daemon run mode
    print("Agent running in background. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping ADR Architect Agent...")
        client.stop()
        if simulator_server:
            simulator_server.shutdown()


if __name__ == "__main__":
    main()
