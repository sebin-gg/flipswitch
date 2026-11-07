import os
import re
import logging
import subprocess
import time
from pathlib import Path
from typing import Optional, Dict, Tuple, List

from switch_client import SwitchAgentClient
from adr_engine import ADREngine, ADRProposal

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ADRArchitect")

# After an ADR is recorded, ignore follow-up chatter in that thread for this long
# unless someone explicitly starts a new decision. Guards against duplicate ADRs.
FINALIZED_THREAD_TTL_SECONDS = 300
NEW_TOPIC_MARKERS = (
    "new adr",
    "new decision",
    "another adr",
    "next adr",
    "next decision",
    "new topic",
)


class ADRArchitectAgent:
    """Collaborative ADR Architect Agent connected via Switch Protocol."""

    def __init__(self, client: SwitchAgentClient, repo_dir: str = ".", adr_dir: str = "docs/adr", engine: Optional[ADREngine] = None):
        self.client = client
        self.repo_dir = Path(repo_dir).resolve()
        self.adr_dir = self.repo_dir / adr_dir
        self.engine = engine or ADREngine()
        # Maps room_id/thread_id to active pending ADRProposal
        self.active_state: Dict[str, ADRProposal] = {}
        # thread_id -> (timestamp, filename) of the last recorded decision
        self.finalized_threads: Dict[str, Tuple[float, str]] = {}
        self.adr_dir.mkdir(parents=True, exist_ok=True)

        # Wire up message callback
        self.client.on_message_callback = self.handle_room_message

    def handle_room_message(self, room_id: str, payload: dict):
        """Processes room messages received from Switch SSE stream."""
        try:
            sender_name = payload.get("sender_name", payload.get("sender", "Teammate"))
            if "architect" in str(sender_name).lower():
                return  # Ignore messages sent by self

            body = payload.get("body", "")
            reply_thread = payload.get("thread_id")
            thread_id = reply_thread or room_id
            addressed = payload.get("addressed", False) or "@architect" in body.lower()

            logger.info("Message in [%s] from %s: %s (addressed=%s)", room_id, sender_name, body[:60], addressed)

            if not addressed:
                return

            # Do not re-record a decision because of follow-up chatter in the same thread.
            last = self.finalized_threads.get(thread_id)
            starts_new_topic = any(marker in body.lower() for marker in NEW_TOPIC_MARKERS)
            if last and time.time() - last[0] < FINALIZED_THREAD_TTL_SECONDS and not starts_new_topic:
                self.client.post_message(
                    room_id,
                    f"🏛️ **ADR Architect**: I already recorded this discussion as `{last[1]}`. "
                    f"To capture a different decision, start with `@architect new ADR ...`.",
                    thread_id=reply_thread,
                )
                return
            if starts_new_topic:
                self.finalized_threads.pop(thread_id, None)

            # Check if this thread has an active proposal waiting for answers
            if thread_id in self.active_state:
                proposal = self.active_state[thread_id]
                logger.info("Active ADR proposal found for thread %s: %s", thread_id, proposal.title)

                clean_text = re.sub(r"@architect\s*", "", body, flags=re.IGNORECASE).strip()

                if any(k in clean_text.lower() for k in ["finalize", "approved", "ship it", "looks good", "commit"]):
                    filename, commit_msg = self.save_and_commit_adr(proposal)
                    del self.active_state[thread_id]
                    self.finalized_threads[thread_id] = (time.time(), filename)
                    summary = (
                        f"🏛️ **ADR Architect**: Finalized and committed to repository! 🎉\n\n"
                        f"- 📄 **ADR Document**: `docs/adr/{filename}`\n"
                        f"- 🔀 **Git Commit**: `{commit_msg}`\n"
                        f"- 📌 **Status**: Accepted\n\n"
                        f"Ready for next architecture topic!"
                    )
                    self.client.post_message(room_id, summary, thread_id=reply_thread)
                    return

                # Otherwise, treat the message as answers to open questions
                user_answers = {}
                for q in list(proposal.open_questions):
                    user_answers[q] = clean_text

                self.engine.refine_with_answers(proposal, user_answers)

                if not proposal.open_questions:
                    # All questions answered! Auto-finalize or request approval
                    filename, commit_msg = self.save_and_commit_adr(proposal)
                    del self.active_state[thread_id]
                    self.finalized_threads[thread_id] = (time.time(), filename)
                    summary = (
                        f"🏛️ **ADR Architect**: All clarifications received. Decision recorded! 🎉\n\n"
                        f"- 📄 **Document**: `docs/adr/{filename}`\n"
                        f"- 🔀 **Git Commit**: `{commit_msg}`\n\n"
                        f"### Final Decision Summary:\n"
                        f"> {proposal.decision}\n\n"
                        f"**Rollback Strategy**: {proposal.rollback_plan}"
                    )
                    self.client.post_message(room_id, summary, thread_id=reply_thread)
                else:
                    remaining_q = "\n".join(f"- {q}" for q in proposal.open_questions)
                    self.client.post_message(
                        room_id,
                        f"🏛️ **ADR Architect**: Updated draft with your inputs. Remaining items needed:\n{remaining_q}",
                        thread_id=reply_thread,
                    )
                return

            # No active proposal in this thread: parse discussion context
            raw_context = self.client.read_context(room_id, limit=30)
            logger.info("Retrieved %d messages from room context for analysis", len(raw_context))

            # Transform raw context to message list for engine (the client already
            # normalizes bridge and simulator payloads to sender/content).
            thread_messages = []
            for item in raw_context:
                if isinstance(item, dict):
                    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
                    msg_body = item.get("content") or item.get("body") or payload.get("body", "")
                    sender = item.get("sender") or item.get("sender_name") or payload.get("sender_name", "Teammate")
                    thread_messages.append({"sender": sender, "content": msg_body})

            # If user included discussion in current message, add it
            clean_body = re.sub(r"@architect\s*", "", body, flags=re.IGNORECASE).strip()
            if clean_body:
                thread_messages.append({"sender": sender_name, "content": clean_body})

            proposal = self.engine.analyze_discussion(thread_messages)

            # Infer a better title from the prompt if the engine fell back to a generic one
            if proposal.title in ["System Architecture Decision", "Architectural Decision Proposal"] and clean_body:
                for line in clean_body.splitlines():
                    if any(w in line.lower() for w in ["database", "storage", "auth", "cache", "api", "framework", "queue", "architecture"]):
                        proposal.title = line.strip()[:80].rsplit(" ", 1)[0].rstrip(" .,:;")
                        break
                else:
                    proposal.title = clean_body[:50].rsplit(" ", 1)[0].rstrip(" .,:;")

            if proposal.open_questions:
                self.active_state[thread_id] = proposal
                questions_formatted = "\n".join(f"{i+1}. **{q}**" for i, q in enumerate(proposal.open_questions))
                reply = (
                    f"🏛️ **ADR Architect**: I analyzed the team discussion for **{proposal.title}**.\n\n"
                    f"I have drafted a preliminary MADR specification. Before recording to git, please clarify:\n\n"
                    f"{questions_formatted}\n\n"
                    f"_Reply directly in this thread with your answers, or type `@architect approve` to record as-is._"
                )
                self.client.post_message(room_id, reply, thread_id=reply_thread)
            else:
                filename, commit_msg = self.save_and_commit_adr(proposal)
                self.finalized_threads[thread_id] = (time.time(), filename)
                summary = (
                    f"🏛️ **ADR Architect**: Discussion analyzed and recorded as ADR! 🎉\n\n"
                    f"- 📄 **Document**: `docs/adr/{filename}`\n"
                    f"- 🔀 **Git Commit**: `{commit_msg}`"
                )
                self.client.post_message(room_id, summary, thread_id=reply_thread)

        except Exception as e:
            logger.exception("Error handling room message: %s", e)
            self.client.post_message(room_id, f"🏛️ **ADR Architect**: Encountered error processing request: {e}")

    def save_and_commit_adr(self, proposal: ADRProposal) -> Tuple[str, str]:
        """Renders MADR markdown, writes file, updates index, and commits to git."""
        self.adr_dir.mkdir(parents=True, exist_ok=True)

        existing_files = list(self.adr_dir.glob("*.md"))
        existing_numbers = []
        for f in existing_files:
            match = re.match(r"^(\d+)-", f.name)
            if match:
                existing_numbers.append(int(match.group(1)))

        next_number = max(existing_numbers, default=0) + 1
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", proposal.title.lower()).strip("-") or "architectural-decision"
        filename = f"{next_number:04d}-{slug}.md"
        file_path = self.adr_dir / filename

        # Render MADR format
        rendered_md = self.engine.render_markdown(proposal, next_number)
        file_path.write_text(rendered_md, encoding="utf-8")

        # Update docs/adr/README.md index
        self.engine.update_adr_index(
            str(self.repo_dir / "docs"), next_number, proposal.title, filename, proposal.status
        )

        # Git commit (argument list, no shell interpolation)
        commit_message = f"docs(adr): record ADR-{next_number:04d}: {proposal.title}"
        rel_adr = file_path.relative_to(self.repo_dir).as_posix()
        rel_readme = (self.adr_dir / "README.md").relative_to(self.repo_dir).as_posix()
        try:
            self._git("add", rel_adr, rel_readme)
            self._git("commit", "-m", commit_message)
            logger.info("Committed %s to git", rel_adr)
        except Exception as ge:
            logger.warning("Git commit failed (file written anyway): %s", ge)

        return filename, commit_message

    def _git(self, *args: str) -> str:
        """Runs a git command in the target repository without a shell."""
        result = subprocess.run(
            ["git", "-C", str(self.repo_dir), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip() or "git command failed")
        return result.stdout
