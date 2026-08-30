"""Bounded, case-specific multi-turn analyst conversation service."""

from __future__ import annotations

from typing import Literal, Protocol

from openai import OpenAI
from pydantic import BaseModel, Field

from copilot.case_store import CaseStore
from copilot.drafting import NEBIUS_BASE_URL
from copilot.guardrails import evaluate_generated_summary, evaluate_policy_answerability
from copilot.models import InvestigationDraft
from copilot.retrieval import RetrievalResult
from copilot.settings import Settings

ConversationRoute = Literal["answer", "clarify", "refuse", "insufficient_evidence"]
PROHIBITED_CHAT_ACTIONS = ("freeze account", "restrict account", "contact customer", "submit smr")


class ConversationRequest(BaseModel):
    question: str = Field(min_length=3, max_length=750)


class ConversationResponse(BaseModel):
    case_id: str
    route: ConversationRoute
    reply: str
    citations: list[str] = Field(default_factory=list)
    history: list[dict[str, str]] = Field(default_factory=list)


class ConversationResponder(Protocol):
    def rewrite(
        self,
        question: str,
        baseline_reply: str,
        draft: InvestigationDraft,
        history: list[dict[str, str]],
    ) -> str: ...


class NebiusConversationResponder:
    """Optional rewrite only; retrieval, routing, and factual controls remain deterministic."""

    def __init__(self, settings: Settings) -> None:
        if settings.nebius_api_key is None:
            raise ValueError("Nebius key is required for conversational generation.")
        self._client = OpenAI(
            base_url=NEBIUS_BASE_URL,
            api_key=settings.nebius_api_key.get_secret_value(),
            timeout=30,
        )
        self._model_name = settings.model_name

    def rewrite(
        self,
        question: str,
        baseline_reply: str,
        draft: InvestigationDraft,
        history: list[dict[str, str]],
    ) -> str:
        response = self._client.chat.completions.create(
            model=self._model_name,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Answer a financial-crime analyst's case question concisely. Only restate "
                        "the provided answer and evidence. Do not make fraud conclusions or direct "
                        "operational actions."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question: {question}\nBaseline answer: {baseline_reply}\n"
                        f"Approved evidence: {' '.join(draft.observed_signals)}\n"
                        f"Prior case conversation: {history}"
                    ),
                },
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Conversation model returned an empty response.")
        return content


def respond_to_case_question(
    case_id: str,
    question: str,
    draft: InvestigationDraft,
    retrieval: RetrievalResult,
    case_store: CaseStore,
    responder: ConversationResponder | None = None,
) -> ConversationResponse:
    """Answer only explain/clarify questions against the current governed case state."""
    normalised = question.lower().strip()
    if any(action in normalised for action in PROHIBITED_CHAT_ACTIONS):
        return _record(
            case_id,
            question,
            "Meridian cannot execute consequential actions. Route that request to an authorised "
            "human process.",
            "refuse",
            [],
            case_store,
        )
    if len(normalised.split()) < 3:
        return _record(
            case_id,
            question,
            "Please ask a specific question about the evidence, policy citations, recommendation, "
            "or missing information for this case.",
            "clarify",
            [],
            case_store,
        )
    gate = evaluate_policy_answerability(
        None, retrieval.assessment, len(retrieval.citations)
    )
    # The case itself already passed the workflow evidence gate; only policy answerability is
    # rechecked for this new question.
    policy_reasons = [
        reason for reason in gate.reasons if "citation" in reason or "confidence" in reason
    ]
    if policy_reasons:
        return _record(
            case_id,
            question,
            "I do not have sufficient approved-policy context to answer that safely. "
            + " ".join(policy_reasons),
            "insufficient_evidence",
            [],
            case_store,
        )
    citation_ids = [citation.policy_id for citation in retrieval.citations]
    if any(word in normalised for word in ("why", "evidence", "signal", "payment")):
        reply = "Current case evidence: " + " ".join(draft.observed_signals[:3])
    elif any(word in normalised for word in ("missing", "gap", "need")):
        limitations = draft.limitations or ["No additional limitation was recorded in the brief."]
        reply = "Recorded limitations: " + " ".join(limitations)
    elif any(word in normalised for word in ("policy", "procedure", "citation")):
        reply = (
            "Relevant approved-policy context was retrieved for this question. "
            f"Citations: {', '.join(citation_ids)}."
        )
    else:
        reply = (
            "I can explain the case evidence, policy citations, recommendation, or "
            "information gaps. "
            "Please make the follow-up more specific."
        )
        return _record(case_id, question, reply, "clarify", [], case_store)
    if responder is not None:
        try:
            candidate = responder.rewrite(
                question, reply, draft, case_store.recent_conversation(case_id)
            )
            if evaluate_generated_summary(candidate, draft).passed:
                reply = candidate
        except Exception:
            pass
    return _record(case_id, question, reply, "answer", citation_ids, case_store)


def conversation_responder_from_settings(settings: Settings) -> ConversationResponder | None:
    if not settings.live_model_enabled or settings.nebius_api_key is None:
        return None
    return NebiusConversationResponder(settings)


def _record(
    case_id: str,
    question: str,
    reply: str,
    route: ConversationRoute,
    citations: list[str],
    case_store: CaseStore,
) -> ConversationResponse:
    case_store.record_conversation_turn(case_id, question, reply, route)
    return ConversationResponse(
        case_id=case_id,
        route=route,
        reply=reply,
        citations=citations,
        history=case_store.recent_conversation(case_id),
    )
