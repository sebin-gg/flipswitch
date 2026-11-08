import datetime
import os
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional


def _mentions(text: str, words: List[str]) -> bool:
    """Whole-word keyword match, so "pro" does not match "protobuf"."""
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


TECH_LABELS = {
    "grpc": "gRPC",
    "rest": "REST",
    "postgresql": "PostgreSQL",
    "clickhouse": "ClickHouse",
    "database": "Database",
    "storage": "Storage",
    "authentication": "Authentication",
    "cache": "Cache",
    "kafka": "Kafka",
    "redis": "Redis",
    "mongodb": "MongoDB",
    "graphql": "GraphQL",
}


@dataclass
class ADRProposal:
    title: str
    status: str = "Proposed"
    context: str = ""
    decision: str = ""
    consequences_positive: List[str] = field(default_factory=list)
    consequences_negative: List[str] = field(default_factory=list)
    alternatives: List[str] = field(default_factory=list)
    rollback_plan: str = ""
    open_questions: List[str] = field(default_factory=list)


class ADREngine:
    """Extracts, refines, and formats Architecture Decision Records (MADR 3.0 standard)."""

    def analyze_discussion(self, thread_messages: List[Dict]) -> ADRProposal:
        """Analyzes a thread of messages from chat, extracting context, decision, trade-offs,

        and detecting missing architectural requirements.
        """
        context_parts = []
        decision_parts = []
        positives = []
        negatives = []
        alternatives = []
        rollback = ""
        topic_candidates = []

        for msg in thread_messages:
            sender = msg.get("sender", "Team")
            text = msg.get("content", "").strip()
            if not text:
                continue

            lower = text.lower()

            # Ignore raw bot mentions or commands
            if lower.startswith("@architect") and len(lower.split()) < 3:
                continue

            # Identify Context / Problem
            if any(w in lower for w in ["need to", "problem", "currently", "challenge", "facing", "requirement", "decide on", "goal"]):
                context_parts.append(f"{sender}: {text}")
                # Infer topic
                for tech in TECH_LABELS:
                    if re.search(rf"\b{re.escape(tech)}\b", lower) and tech not in topic_candidates:
                        topic_candidates.append(tech)

            # Identify Decision / Proposed Solution
            if _mentions(lower, ["propose", "recommend", "should use", "we use", "we will use", "go with", "decided to", "decision is", "selected", "let's use", "lets use"]):
                decision_parts.append(text)
            elif not decision_parts and _mentions(lower, ["best choice", "handles our"]):
                decision_parts.append(text)

            # Identify Positive consequences / Pros
            if _mentions(lower, ["pro", "pros", "advantage", "advantageous", "benefit", "benefits", "upside", "good because", "strength", "fast", "mature", "performance", "cheap"]):
                positives.append(text)

            # Identify Negative consequences / Cons / Trade-offs
            if _mentions(lower, ["con", "cons", "drawback", "drawbacks", "downside", "risk", "disadvantage", "challenge", "challenges", "tuning", "cost", "costs", "overhead", "trade-off", "tradeoff", "trade-offs", "harder"]):
                negatives.append(text)

            # Identify Alternatives
            if any(w in lower for w in ["alternative", "instead of", "considered", "evaluated", "versus", "vs "]):
                alternatives.append(text)

            # Identify Rollback / Fallback
            if any(w in lower for w in ["rollback", "fallback", "revert", "failover", "undo"]):
                rollback = text

        # Default fallbacks if conversation was informal
        if not context_parts and thread_messages:
            context_parts.append(thread_messages[0].get("content", ""))
        if not decision_parts and len(thread_messages) > 1:
            decision_parts.append(thread_messages[1].get("content", ""))

        # Synthesize Title
        if topic_candidates:
            labels = [TECH_LABELS.get(t, t.capitalize()) for t in topic_candidates[:2]]
            title = f"Selection of {' & '.join(labels)} for System Architecture"
        elif decision_parts:
            first_line = decision_parts[0].split("\n")[0]
            first_line = re.sub(r"^[A-Za-z0-9_-]+:\s*", "", first_line)
            # A chat command is not the decision: "@architect new ADR: ...".
            first_line = re.sub(
                r"^@architect\s+(?:new\s+adr[:\s-]*)?", "", first_line, flags=re.IGNORECASE
            )
            first_line = first_line.split(". ")[0].strip()
            if len(first_line) > 10:
                # Cut on a word boundary: "... mature operators, pl" reads like a bug.
                title = first_line[:60].rsplit(" ", 1)[0].rstrip(" .,:;") or first_line[:60]
            else:
                title = "System Architecture Decision"
        else:
            title = "System Architecture Decision"

        open_questions = []

        # Detect missing critical architectural guardrails
        if not rollback:
            open_questions.append("What is the rollback or mitigation plan if this technical decision encounters failure in production?")
        if not negatives:
            open_questions.append("What operational drawbacks, maintenance costs, or trade-offs does the team anticipate?")
        if not positives:
            open_questions.append("What primary performance or developer-velocity benefits justify this decision?")

        proposal = ADRProposal(
            title=title,
            status="Proposed",
            context="\n".join(context_parts).strip() or "Architectural discussion held in team chat channel.",
            decision="\n".join(decision_parts).strip() or "Team selected proposed architecture based on consensus.",
            consequences_positive=positives,
            consequences_negative=negatives,
            alternatives=alternatives or ["Status quo / custom in-house implementation"],
            rollback_plan=rollback,
            open_questions=open_questions
        )

        return proposal

    def refine_with_answers(self, proposal: ADRProposal, user_answers: Dict[str, str]) -> ADRProposal:
        """Refines the proposal with team answers from chat.

        The answer text is classified first, so a single reply like
        "our rollback is X" fills the rollback slot even when the agent asked
        several questions at once.
        """
        for question, answer in user_answers.items():
            clean_ans = answer.strip()
            if not clean_ans:
                continue

            ans_lower = clean_ans.lower()
            q_lower = question.lower()
            if any(k in ans_lower for k in ["rollback", "fall back", "fallback", "revert", "failover", "fail over"]):
                proposal.rollback_plan = clean_ans
            elif any(k in ans_lower for k in ["trade-off", "tradeoff", "drawback", "downside", "overhead", "cost", "risk"]):
                if clean_ans not in proposal.consequences_negative:
                    proposal.consequences_negative.append(clean_ans)
            elif any(k in ans_lower for k in ["benefit", "advantage", "faster", "cheaper", "velocity", "frees us"]):
                if clean_ans not in proposal.consequences_positive:
                    proposal.consequences_positive.append(clean_ans)
            elif "rollback" in q_lower or "failure" in q_lower or "mitigation" in q_lower:
                proposal.rollback_plan = clean_ans
            elif "drawback" in q_lower or "trade-off" in q_lower or "negative" in q_lower:
                proposal.consequences_negative.append(clean_ans)
            elif "benefit" in q_lower or "positive" in q_lower:
                proposal.consequences_positive.append(clean_ans)

        # Clear answered open questions
        proposal.open_questions = [
            q for q in proposal.open_questions if q not in user_answers
        ]
        if not proposal.open_questions:
            proposal.status = "Accepted"

        return proposal

    def render_markdown(self, proposal: ADRProposal, adr_id: int) -> str:
        """Renders MADR (Markdown Architecture Decision Record) format."""
        positives_md = "\n".join(f"* Good, because {item}" for item in proposal.consequences_positive) or "* Positive impact on velocity and system stability."
        negatives_md = "\n".join(f"* Bad, because {item}" for item in proposal.consequences_negative) or "* Operational overhead and monitoring required."
        alternatives_md = "\n".join(f"* {alt}" for alt in proposal.alternatives) or "* None evaluated."

        return f"""# ADR-{adr_id:04d}: {proposal.title}

* **Status:** {proposal.status}
* **Deciders:** Engineering Team (via Switch Room)
* **Date:** {datetime.date.today().isoformat()}

## Context and Problem Statement
{proposal.context}

## Decision Outcome
Chosen option: **{proposal.decision}**

### Positive Consequences
{positives_md}

### Negative Consequences / Trade-offs
{negatives_md}

## Pros and Cons of the Options
### Considered Alternatives
{alternatives_md}

## Rollback & Failure Strategy
{proposal.rollback_plan or "Standard blue/green rollback to previous release."}

---
*Generated collaboratively by Switch ADR Architect Agent.*
"""

    def update_adr_index(self, docs_dir: str, adr_id: int, title: str, filename: str, status: str = "Accepted") -> None:
        """Updates docs/adr/README.md with the new entry."""
        index_file = os.path.join(docs_dir, "adr", "README.md")
        os.makedirs(os.path.dirname(index_file), exist_ok=True)

        if not os.path.exists(index_file):
            with open(index_file, "w", encoding="utf-8") as f:
                f.write("# Architecture Decision Records (ADRs)\n\n")
                f.write("All architecture decisions recorded live from team chat rooms via **Switch**.\n\n")
                f.write("| ADR | Title | Status | Link |\n")
                f.write("|:---:|:------|:------:|:----:|\n")

        with open(index_file, "r", encoding="utf-8") as f:
            content = f.read()

        row = f"| ADR-{adr_id:04d} | {title} | {status} | [{filename}]({filename}) |\n"
        if f"ADR-{adr_id:04d}" not in content:
            with open(index_file, "a", encoding="utf-8") as f:
                f.write(row)
