"""Typed contracts for workflow state, tools, gates, and analyst review."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Recommendation(StrEnum):
    NO_FURTHER_ACTION = "no_further_action_recommended"
    FURTHER_INVESTIGATION = "further_investigation_or_monitoring"
    HUMAN_ESCALATION = "human_escalation_required"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ConfidenceBand(StrEnum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


class IntakeIntent(StrEnum):
    INVESTIGATE_PAYMENT_ALERT = "investigate_payment_alert"
    EXPLAIN_POLICY = "explain_policy"
    RETRIEVE_CASE_STATUS = "retrieve_case_status"
    RECORD_ANALYST_REVIEW = "record_analyst_review"
    UNKNOWN_OR_AMBIGUOUS = "unknown_or_ambiguous"
    UNSAFE_OR_PROHIBITED = "unsafe_or_prohibited"


class IntakeDecision(BaseModel):
    intent: IntakeIntent
    case_id: str | None = None
    confidence: float = Field(ge=0, le=1)
    missing_fields: list[str] = Field(default_factory=list)
    response_mode: Literal["route", "clarify", "refuse", "human_review"]
    explanation: str


class Alert(BaseModel):
    case_id: str
    alert_id: str
    alert_type: Literal["unusual_outbound_payment"]
    account_id: str
    transaction_id: str
    reason: str
    severity: Severity
    created_at: datetime


class AccountProfile(BaseModel):
    account_id: str
    customer_reference: str
    account_age_days: int = Field(ge=0)
    customer_risk_tier: str
    usual_outbound_payment_max_aud: float = Field(ge=0)
    usual_monthly_outbound_aud: float = Field(ge=0)
    kyc_status: str


class Transaction(BaseModel):
    transaction_id: str
    account_id: str
    occurred_at: datetime
    direction: Literal["inbound", "outbound"]
    amount_aud: float = Field(gt=0)
    channel: str
    counterparty_reference: str
    payment_rail: str
    first_time_counterparty: bool
    description: str


class EvidenceItem(BaseModel):
    evidence_id: str
    source_type: Literal["transaction", "account", "tool_error"]
    source_reference: str
    finding: str
    confidence: float = Field(ge=0, le=1)


class PolicyCitation(BaseModel):
    policy_id: str
    policy_version: str
    section: str
    excerpt: str


class RetrievalAssessment(BaseModel):
    """Explainable confidence assessment for approved-policy retrieval."""

    top_keyword_score: int = Field(ge=0)
    relevant_citation_count: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    confidence_band: ConfidenceBand
    backend: Literal["local", "pinecone"] = "local"
    search_mode: Literal["lexical", "semantic", "hybrid"] = "lexical"
    fallback_used: bool = False
    reranker_used: bool = False
    candidate_count: int = Field(ge=0, default=0)
    rationale: list[str] = Field(default_factory=list)


class AgentPacket(BaseModel):
    """Portable A2A-style message exchanged between bounded specialist roles."""

    case_id: str
    agent_name: Literal["evidence_agent", "policy_agent", "synthesis_agent"]
    status: Literal["complete", "partial", "failed"]
    findings: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    citations: list[PolicyCitation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    recommended_next_step: str


class InvestigationDraft(BaseModel):
    case_id: str
    summary: str
    observed_signals: list[str]
    evidence_ids: list[str]
    policy_citations: list[PolicyCitation]
    limitations: list[str]
    recommendation: Recommendation
    confidence: float = Field(ge=0, le=1)
    confidence_band: ConfidenceBand = ConfidenceBand.LOW
    confidence_rationale: list[str] = Field(default_factory=list)


class GateResult(BaseModel):
    gate_name: str
    passed: bool
    reasons: list[str] = Field(default_factory=list)


class AnalystDecision(BaseModel):
    case_id: str
    decision: Literal["approved", "edited", "more_evidence", "insufficient_evidence", "escalated"]
    rationale: str = Field(min_length=3, max_length=1000)
    decided_at: datetime
