import os
import re
import logging
from pathlib import Path
from typing import Optional, Dict, Tuple, List

from switch_client import SwitchAgentClient
from adr_engine import ADREngine, ADRProposal

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ADRArchitect")


class ADRArchitectAgent:
    """Collaborative ADR Architect Agent connected via Switch Protocol."""

    def __init__(self, client: SwitchAgentClient, repo_dir: str = ".", adr_dir: str = "docs/adr"):
        self.client = client
        self.repo_dir = Path(repo_dir).resolve()
        self.adr_dir = self.repo_dir / adr_dir
        self.engine = ADREngine()
        # Maps room_id/thread_id to active pending ADRProposal
        self.active_state: Dict[str, ADRProposal] = {}
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
            thread_id = payload.get("thread_id") or room_id
            addressed = payload.get("addressed", False) or "@architect" in body.lower()

            logger.info("Message in [%s] from %s: %s (addressed=%s)", room_id, sender_name, body[:60], addressed)

            if not addressed:
                return

            # Check if this thread has an active proposal waiting for answers
            if thread_id in self.active_state:
                proposal = self.active_state[thread_id]
                logger.info("Active ADR proposal found for thread %s: %s", thread_id, proposal.title)

                clean_text = re.sub(r"@architect\s*", "", body, flags=re.IGNORECASE).strip()

                if any(k in clean_text.lower() for k in ["finalize", "approved", "ship it", "looks good", "commit"]):
                    filename, commit_msg = self.save_and_commit_adr(proposal)
                    del self.active_state[thread_id]
                    summary = (
                        f"🏛️ **ADR Architect**: Finalized and committed to repository! 🎉\n\n"
                        f"- 📄 **ADR Document**: `docs/adr/{filename}`\n"
                        f"- 🔀 **Git Commit**: `{commit_msg}`\n"
                        f"- 📌 **Status**: Accepted\n\n"
                        f"Ready for next architecture topic!"
                    )
                    self.client.post_message(room_id, summary, thread_id=thread_id)
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
                    summary = (
                        f"🏛️ **ADR Architect**: All clarifications received. Decision recorded! 🎉\n\n"
                        f"- 📄 **Document**: `docs/adr/{filename}`\n"
                        f"- 🔀 **Git Commit**: `{commit_msg}`\n\n"
                        f"### Final Decision Summary:\n"
                        f"> {proposal.decision}\n\n"
                        f"**Rollback Strategy**: {proposal.rollback_plan}"
                    )
                    self.client.post_message(room_id, summary, thread_id=thread_id)
                else:
                    remaining_q = "\n".join(f"- {q}" for q in proposal.open_questions)
                    self.client.post_message(
                        room_id,
                        f"🏛️ **ADR Architect**: Updated draft with your inputs. Remaining items needed:\n{remaining_q}",
                        thread_id=thread_id,
                    )
                return

            # No active proposal in this thread: parse discussion context
            raw_context = self.client.read_context(room_id, limit=30)
            logger.info("Retrieved %d messages from room context for analysis", len(raw_context))

            # Transform raw context to message list for engine
            thread_messages = []
            for item in raw_context:
                if isinstance(item, dict):
                    msg_body = item.get("payload", {}).get("body", item.get("body", item.get("content", "")))
                    sender = item.get("payload", {}).get("sender_name", item.get("sender_name", "Teammate"))
                    thread_messages.append({"sender": sender, "content": msg_body})

            # If user included discussion in current message, add it
            clean_body = re.sub(r"@architect\s*", "", body, flags=re.IGNORECASE).strip()
            if clean_body:
                thread_messages.append({"sender": sender_name, "content": clean_body})

            proposal = self.engine.analyze_discussion(thread_messages)

            # Infer better title from prompt or context if default
            for line in clean_body.splitlines():
                if any(w in line.lower() for w in ["database", "storage", "auth", "cache", "api", "framework", "queue", "architecture"]):
                    proposal.title = line.strip()
                    break
            if proposal.title == "Architectural Decision Proposal" and clean_body:
                proposal.title = clean_body[:50]

            if proposal.open_questions:
                self.active_state[thread_id] = proposal
                questions_formatted = "\n".join(f"{i+1}. **{q}**" for i, q in enumerate(proposal.open_questions))
                reply = (
                    f"🏛️ **ADR Architect**: I analyzed the team discussion for **{proposal.title}**.\n\n"
                    f"I have drafted a preliminary MADR specification. Before recording to git, please clarify:\n\n"
                    f"{questions_formatted}\n\n"
                    f"_Reply directly in this thread with your answers, or type `@architect approve` to record as-is._"
                )
                self.client.post_message(room_id, reply, thread_id=thread_id)
            else:
                filename, commit_msg = self.save_and_commit_adr(proposal)
                summary = (
                    f"🏛️ **ADR Architect**: Discussion analyzed and recorded as ADR! 🎉\n\n"
                    f"- 📄 **Document**: `docs/adr/{filename}`\n"
                    f"- 🔀 **Git Commit**: `{commit_msg}`"
                )
                self.client.post_message(room_id, summary, thread_id=thread_id)

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
        self.engine.update_adr_index(str(self.repo_dir / "docs"), next_number, proposal.title, filename)

        # Git commit
        commit_message = f"docs(adr): record ADR-{next_number:04d}: {proposal.title}"
        try:
            rel_adr = file_path.relative_to(self.repo_dir)
            rel_readme = (self.adr_dir / "README.md").relative_to(self.repo_dir)
            os.system(f'git -C "{self.repo_dir}" add "{rel_adr}" "{rel_readme}"')
            os.system(f'git -C "{self.repo_dir}" commit -m "{commit_message}"')
        except Exception as ge:
            logger.warning("Git commit fallback: %s", ge)

        return filename, commit_message
