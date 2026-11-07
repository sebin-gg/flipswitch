"""Smart ADR engine: LLM synthesis with a deterministic fallback.

The smart engine asks an OpenAI-compatible chat-completions endpoint to turn a
messy team-chat debate into a structured MADR proposal. If no API key is
configured, or the provider errors out, it silently degrades to the keyword
engine in :mod:`adr_engine`, so the demo and test suite keep working offline.

Configuration (environment variables):
    ADR_API_KEY / OPENAI_API_KEY   API key for the model provider.
    ADR_MODEL                      Model name (default: gpt-4.1).
    ADR_LLM_BASE_URL               OpenAI-compatible base URL.
"""

import json
import logging
import os
from typing import Dict, List, Optional

import requests

from adr_engine import ADREngine, ADRProposal

logger = logging.getLogger("ADRArchitect.SmartEngine")

DEFAULT_MODEL = "gpt-4.1"
DEFAULT_BASE_URL = "https://api.openai.com/v1"

SYSTEM_PROMPT = """You are a senior software architect who records Architecture Decision Records (MADR 3.0).
You receive a team chat transcript. Extract the real decision, the context, the trade-offs
and the alternatives actually discussed. Never invent vendors or facts that are not implied
by the transcript. Identify genuine gaps in the discussion (missing rollback strategy,
unstated operational trade-offs, missing alternatives) as clarifying questions.

Reply with a single JSON object using exactly these keys:
{
  "title": "short, specific decision title (max 12 words, no 'ADR' prefix)",
  "context": "2-4 sentence problem statement",
  "decision": "1-3 sentence chosen option",
  "positive_consequences": ["specific benefit", "..."],
  "negative_consequences": ["specific trade-off or risk", "..."],
  "alternatives": ["option considered and why it lost", "..."],
  "rollback_plan": "concrete mitigation/rollback, or empty string if the team never stated one",
  "open_questions": ["question the team must answer before this is final", "..."]
}
Return only the JSON object."""


class LLMClient:
    """Minimal client for any OpenAI-compatible ``/chat/completions`` endpoint."""

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 45,
    ):
        self.model = model or os.getenv("ADR_MODEL") or DEFAULT_MODEL
        self.api_key = api_key or os.getenv("ADR_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.base_url = (
            base_url
            or os.getenv("ADR_LLM_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or DEFAULT_BASE_URL
        ).rstrip("/")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def describe(self) -> str:
        if not self.available:
            return "heuristic engine (set ADR_API_KEY or OPENAI_API_KEY to enable the smart model)"
        return f"smart model {self.model} @ {self.base_url}"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if not self.available:
            raise RuntimeError("No LLM API key configured")

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }

        resp = requests.post(url, json=body, headers=headers, timeout=self.timeout)
        if resp.status_code == 400:
            # Some OpenAI-compatible providers reject response_format; retry plainly.
            body.pop("response_format", None)
            resp = requests.post(url, json=body, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


class SmartADREngine(ADREngine):
    """ADR engine that uses an LLM when configured, keyword heuristics otherwise."""

    def __init__(self, llm: Optional[LLMClient] = None):
        super().__init__()
        self.llm = llm or LLMClient()

    @property
    def using_llm(self) -> bool:
        return self.llm.available

    def describe(self) -> str:
        return self.llm.describe()

    def analyze_discussion(self, thread_messages: List[Dict]) -> ADRProposal:
        if not self.llm.available:
            return super().analyze_discussion(thread_messages)
        try:
            payload = self._analyze_with_llm(thread_messages)
        except Exception as exc:  # network error, bad JSON, provider outage...
            logger.warning("Smart model failed (%s); using heuristic fallback.", exc)
            return super().analyze_discussion(thread_messages)
        return self._to_proposal(payload, thread_messages)

    def _analyze_with_llm(self, thread_messages: List[Dict]) -> Dict:
        transcript = "\n".join(
            f"{m.get('sender', 'Teammate')}: {m.get('content', '').strip()}"
            for m in thread_messages
            if m.get("content", "").strip()
        )
        raw = self.llm.complete(SYSTEM_PROMPT, f"Team chat transcript:\n\n{transcript}")
        payload = self._parse_json(raw)
        if not isinstance(payload, dict):
            raise ValueError("Model did not return a JSON object")
        return payload

    @staticmethod
    def _parse_json(raw: str) -> Dict:
        text = (raw or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("No JSON object in model response")
        return json.loads(text[start : end + 1])

    def _to_proposal(self, payload: Dict, thread_messages: List[Dict]) -> ADRProposal:
        def items(key: str) -> List[str]:
            value = payload.get(key) or []
            if isinstance(value, str):
                value = [value]
            return [str(v).strip() for v in value if str(v).strip()]

        def text(key: str) -> str:
            return str(payload.get(key) or "").strip()

        proposal = ADRProposal(
            title=text("title") or "System Architecture Decision",
            status="Proposed",
            context=text("context"),
            decision=text("decision"),
            consequences_positive=items("positive_consequences"),
            consequences_negative=items("negative_consequences"),
            alternatives=items("alternatives"),
            rollback_plan=text("rollback_plan"),
            open_questions=items("open_questions"),
        )

        # Fall back to heuristics for anything the model left blank.
        baseline = super().analyze_discussion(thread_messages)
        proposal.title = proposal.title[:90] or baseline.title
        proposal.context = proposal.context or baseline.context
        proposal.decision = proposal.decision or baseline.decision
        proposal.consequences_positive = proposal.consequences_positive or baseline.consequences_positive
        proposal.consequences_negative = proposal.consequences_negative or baseline.consequences_negative
        proposal.alternatives = proposal.alternatives or baseline.alternatives

        if not proposal.rollback_plan:
            question = "What is the rollback or mitigation plan if this decision fails in production?"
            if question not in proposal.open_questions:
                proposal.open_questions.append(question)
        if not proposal.consequences_negative:
            question = "What operational drawbacks or trade-offs does the team accept with this choice?"
            if question not in proposal.open_questions:
                proposal.open_questions.append(question)
        return proposal
