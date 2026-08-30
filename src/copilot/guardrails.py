"""Deterministic gates that protect the human-review boundary."""

from __future__ import annotations

import re

from copilot.models import AgentPacket, GateResult, InvestigationDraft, RetrievalAssessment

PROHIBITED_ACTIONS = (
    "freeze account",
    "restrict account",
    "contact the customer",
    "submit an smr",
    "customer committed fraud",
)


def evaluate_draft(draft: InvestigationDraft) -> list[GateResult]:
    """Run deterministic safety and evidence checks before analyst review."""
    required_evidence = GateResult(
        gate_name="required_evidence",
        passed=len(draft.evidence_ids) >= 3,
        reasons=[]
        if len(draft.evidence_ids) >= 3
        else ["Fewer than three evidence items were cited."],
    )
    citations = GateResult(
        gate_name="policy_citations",
        passed=bool(draft.policy_citations),
        reasons=[] if draft.policy_citations else ["No approved policy citation was attached."],
    )
    confidence_floor = GateResult(
        gate_name="confidence_floor",
        passed=draft.confidence >= 0.6,
        reasons=[]
        if draft.confidence >= 0.6
        else ["Combined evidence and retrieval confidence is below the 0.60 minimum."],
    )
    draft_text = " ".join(
        [draft.summary, *draft.observed_signals, *draft.limitations, draft.recommendation.value]
    ).lower()
    prohibited = [phrase for phrase in PROHIBITED_ACTIONS if phrase in draft_text]
    action_boundary = GateResult(
        gate_name="prohibited_actions",
        passed=not prohibited,
        reasons=[f"Prohibited wording detected: {phrase}" for phrase in prohibited],
    )
    pii_pattern = re.compile(r"\b\d{6,}\b|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
    pii_matches = pii_pattern.findall(draft_text)
    pii = GateResult(
        gate_name="pii_minimisation",
        passed=not pii_matches,
        reasons=["Potential direct identifier detected in draft output."] if pii_matches else [],
    )
    return [required_evidence, citations, confidence_floor, action_boundary, pii]


def evaluate_generated_summary(
    generated_summary: str, deterministic_baseline: InvestigationDraft
) -> GateResult:
    """Check that an optional model rewrite stays grounded in approved context.

    This deliberately uses transparent deterministic checks at runtime.  It is a
    guardrail, not a claim that a lexical match proves factual correctness.
    """
    approved_text = " ".join(
        [
            deterministic_baseline.summary,
            *deterministic_baseline.observed_signals,
            *deterministic_baseline.limitations,
            *(citation.excerpt for citation in deterministic_baseline.policy_citations),
        ]
    ).lower()
    generated_lower = generated_summary.lower()
    reasons: list[str] = []
    prohibited = [phrase for phrase in PROHIBITED_ACTIONS if phrase in generated_lower]
    if prohibited:
        reasons.append(f"Prohibited operational or fraud claim: {', '.join(prohibited)}.")
    if re.search(r"\b(confirmed scam|confirmed fraud|definitely fraudulent)\b", generated_lower):
        reasons.append("Generated summary asserted an unverified fraud conclusion.")
    if re.search(r"\b\d{6,}\b|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", generated_summary):
        reasons.append("Generated summary contains a potential direct identifier.")

    approved_numbers = {
        value.replace(",", "")
        for value in re.findall(r"\b\d[\d,]*(?:\.\d+)?\b", approved_text)
    }
    generated_numbers = {
        value.replace(",", "")
        for value in re.findall(r"\b\d[\d,]*(?:\.\d+)?\b", generated_summary)
    }
    unsupported_numbers = generated_numbers - approved_numbers
    if unsupported_numbers:
        reasons.append("Generated summary introduced unsupported numeric facts.")

    ignored_tokens = {
        "about", "after", "analyst", "and", "approved", "assessment", "case", "customer",
        "draft", "evidence", "for", "from", "human", "investigation", "is", "it", "of",
        "or", "payment", "review", "the", "this", "to", "was", "with",
    }
    generated_tokens = set(re.findall(r"[a-z]{4,}", generated_lower)) - ignored_tokens
    approved_tokens = set(re.findall(r"[a-z]{4,}", approved_text)) - ignored_tokens
    overlap = generated_tokens & approved_tokens
    if len(overlap) < 3:
        reasons.append("Generated summary has insufficient lexical grounding in approved context.")
    return GateResult(
        gate_name="generation_groundedness",
        passed=not reasons,
        reasons=reasons,
    )


def evaluate_policy_answerability(
    evidence: AgentPacket | None,
    retrieval: RetrievalAssessment | None,
    citation_count: int,
) -> GateResult:
    """Decide whether retrieved approved policy can support a draft at all.

    This is deliberately positioned before generation: a fluent answer cannot
    compensate for weak approved-policy context.
    """
    reasons: list[str] = []
    if evidence is None or len(evidence.evidence) < 3:
        reasons.append("At least three evidence items are required before drafting.")
    if citation_count < 2:
        reasons.append("At least two approved-policy citations are required before drafting.")
    if retrieval is None or retrieval.confidence < 0.6:
        reasons.append(
            "Approved-policy retrieval confidence is below the 0.60 answerability floor."
        )
    elif retrieval.fallback_used and retrieval.confidence < 0.8:
        reasons.append(
            "Fallback policy retrieval did not meet the stricter 0.80 answerability floor."
        )
    return GateResult(gate_name="policy_answerability", passed=not reasons, reasons=reasons)
