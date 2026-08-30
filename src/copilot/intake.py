"""Transparent intake classification for analyst requests."""

from __future__ import annotations

import re

from copilot.models import IntakeDecision, IntakeIntent

CASE_PATTERN = re.compile(r"\bCASE-AU-\d{3}\b", re.IGNORECASE)
PROHIBITED_REQUESTS = ("freeze account", "restrict account", "contact customer", "submit smr")


def classify_intent(request: str) -> IntakeDecision:
    """Classify a request without LLM ambiguity or hidden tool execution."""
    normalised = request.lower().strip()
    case_match = CASE_PATTERN.search(request)
    case_id = case_match.group(0).upper() if case_match else None
    if any(phrase in normalised for phrase in PROHIBITED_REQUESTS):
        return IntakeDecision(
            intent=IntakeIntent.UNSAFE_OR_PROHIBITED,
            case_id=case_id,
            confidence=1.0,
            response_mode="refuse",
            explanation=(
                "This copilot cannot carry out consequential actions; "
                "route the request to an authorised human process."
            ),
        )
    if any(word in normalised for word in ("investigate", "investigation", "alert")):
        if not case_id:
            return IntakeDecision(
                intent=IntakeIntent.INVESTIGATE_PAYMENT_ALERT,
                confidence=0.85,
                missing_fields=["case_id"],
                response_mode="clarify",
                explanation="Provide a synthetic case ID before an investigation can start.",
            )
        return IntakeDecision(
            intent=IntakeIntent.INVESTIGATE_PAYMENT_ALERT,
            case_id=case_id,
            confidence=0.98,
            response_mode="route",
            explanation="Route to the governed payment-alert investigation workflow.",
        )
    if any(word in normalised for word in ("policy", "procedure", "sop")):
        return IntakeDecision(
            intent=IntakeIntent.EXPLAIN_POLICY,
            case_id=case_id,
            confidence=0.9,
            response_mode="route" if case_id else "clarify",
            missing_fields=[] if case_id else ["policy question or case context"],
            explanation=(
                "Retrieve approved policy only after the policy question is sufficiently specific."
            ),
        )
    if "status" in normalised:
        return IntakeDecision(
            intent=IntakeIntent.RETRIEVE_CASE_STATUS,
            case_id=case_id,
            confidence=0.95 if case_id else 0.7,
            response_mode="route" if case_id else "clarify",
            missing_fields=[] if case_id else ["case_id"],
            explanation="Case status is read-only and requires a case ID.",
        )
    return IntakeDecision(
        intent=IntakeIntent.UNKNOWN_OR_AMBIGUOUS,
        case_id=case_id,
        confidence=0.2,
        response_mode="clarify",
        explanation=(
            "I can investigate a payment alert, explain approved policy, or retrieve a case status."
        ),
    )
