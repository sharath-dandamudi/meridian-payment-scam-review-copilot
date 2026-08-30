"""Small, governed LangGraph workflow for a payment-alert investigation."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from time import perf_counter
from typing import Literal, Protocol, TypedDict, cast

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langsmith import trace

from copilot.drafting import DraftGenerator
from copilot.errors import CopilotError
from copilot.guardrails import (
    evaluate_draft,
    evaluate_generated_summary,
    evaluate_policy_answerability,
)
from copilot.mcp_gateway import FraudDataGateway
from copilot.metrics import (
    ANSWERABILITY_GATES,
    GATE_FAILURES,
    MODEL_DRAFT_DURATION,
    MODEL_DRAFTS,
    WORKFLOW_DURATION,
    WORKFLOWS,
    metrics_enabled,
)
from copilot.models import (
    AgentPacket,
    Alert,
    ConfidenceBand,
    EvidenceItem,
    GateResult,
    InvestigationDraft,
    Recommendation,
    RetrievalAssessment,
)
from copilot.observability import WorkflowTelemetry, request_id_context
from copilot.retrieval import PolicyRetriever, RetrievalResult

workflow_progress_callback: ContextVar[Callable[[str], None] | None] = ContextVar(
    "workflow_progress_callback", default=None
)


class PolicyRetrievalBackend(Protocol):
    def retrieve_with_assessment(self, query: str, top_k: int = 2) -> RetrievalResult: ...


class InvestigationState(TypedDict, total=False):
    case_id: str
    control_mode: Literal["policy_source_unavailable"]
    alert: Alert
    evidence_packet: AgentPacket
    policy_packet: AgentPacket
    retrieval_assessment: RetrievalAssessment
    answerability_gate: GateResult
    draft: InvestigationDraft
    gate_results: list[GateResult]
    generation_gate: GateResult
    route: Literal["human_review", "insufficient_evidence"]
    errors: list[str]
    trace_id: str


class InvestigationWorkflow:
    """A bounded graph with deterministic specialist nodes and checkpointing."""

    def __init__(
        self,
        fixtures_dir: Path,
        policy_dir: Path,
        checkpoint_path: Path | None = None,
        draft_generator: DraftGenerator | None = None,
        retriever: PolicyRetrievalBackend | None = None,
    ) -> None:
        self.gateway = FraudDataGateway(fixtures_dir)
        self.retriever: PolicyRetrievalBackend = retriever or PolicyRetriever(policy_dir)
        self.draft_generator = draft_generator
        self.checkpoint_path = checkpoint_path or Path("artifacts/workflow_checkpoints.sqlite")
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self._checkpoint_connection = sqlite3.connect(self.checkpoint_path, check_same_thread=False)
        self.checkpointer = SqliteSaver(self._checkpoint_connection)
        self.checkpointer.setup()
        self.graph = self._build().compile(checkpointer=self.checkpointer)

    def _build(self) -> StateGraph[InvestigationState]:
        graph = StateGraph(InvestigationState)
        graph.add_node("validate_alert", self.validate_alert)
        graph.add_node("collect_evidence", self.collect_evidence)
        graph.add_node("retrieve_policy", self.retrieve_policy)
        graph.add_node("assess_answerability", self.assess_answerability)
        graph.add_node("synthesise_case", self.synthesise_case)
        graph.add_node("run_gates", self.run_gates)
        graph.add_node("prepare_human_review", self.prepare_human_review)
        graph.add_node("mark_insufficient_evidence", self.mark_insufficient_evidence)
        graph.add_edge(START, "validate_alert")
        graph.add_edge("validate_alert", "collect_evidence")
        graph.add_edge("collect_evidence", "retrieve_policy")
        graph.add_edge("retrieve_policy", "assess_answerability")
        graph.add_conditional_edges(
            "assess_answerability",
            self.route_after_answerability,
            {
                "synthesise_case": "synthesise_case",
                "insufficient_evidence": "mark_insufficient_evidence",
            },
        )
        graph.add_edge("synthesise_case", "run_gates")
        graph.add_conditional_edges(
            "run_gates",
            self.route_after_gates,
            {
                "human_review": "prepare_human_review",
                "insufficient_evidence": "mark_insufficient_evidence",
            },
        )
        graph.add_edge("prepare_human_review", END)
        graph.add_edge("mark_insufficient_evidence", END)
        return graph

    def invoke(
        self,
        case_id: str,
        record_metrics: bool = True,
        progress_callback: Callable[[str], None] | None = None,
        control_mode: Literal["policy_source_unavailable"] | None = None,
    ) -> InvestigationState:
        thread_id = f"{case_id}:control:{control_mode}" if control_mode else case_id
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        telemetry = WorkflowTelemetry(case_id)
        telemetry.start()
        started_at = perf_counter()
        metric_token = metrics_enabled.set(record_metrics)
        progress_token = workflow_progress_callback.set(progress_callback)
        try:
            if record_metrics:
                with trace(
                    "meridian_investigation",
                    run_type="chain",
                    inputs={"case_id": case_id},
                    tags=["meridian", "synthetic-data", "human-review"],
                    metadata={
                        "workflow_version": "0.1.0",
                        "request_id": request_id_context.get(),
                    },
                ) as root_run:
                    initial_state: InvestigationState = {"case_id": case_id, "errors": []}
                    if control_mode is not None:
                        initial_state["control_mode"] = control_mode
                    state = cast(
                        InvestigationState, self.graph.invoke(initial_state, config=config)
                    )
                    root_run.outputs = {
                        "route": state.get("route"),
                        "gate_failure_count": sum(
                            not gate.passed for gate in state.get("gate_results", [])
                        ),
                    }
                    state["trace_id"] = str(root_run.id)
            else:
                initial_state = {"case_id": case_id, "errors": []}
                if control_mode is not None:
                    initial_state["control_mode"] = control_mode
                state = cast(InvestigationState, self.graph.invoke(initial_state, config=config))
        finally:
            metrics_enabled.reset(metric_token)
            workflow_progress_callback.reset(progress_token)
        gate_failures = sum(not gate.passed for gate in state.get("gate_results", []))
        if record_metrics:
            for gate in state.get("gate_results", []):
                if not gate.passed:
                    GATE_FAILURES.labels(gate_name=gate.gate_name).inc()
        route = state.get("route", "insufficient_evidence")
        if record_metrics:
            WORKFLOWS.labels(route=route).inc()
            WORKFLOW_DURATION.observe(perf_counter() - started_at)
        telemetry.completed(route, state.get("draft"), gate_failures)
        return state

    def latest_checkpoint(self, case_id: str) -> InvestigationState:
        """Return persisted graph state for troubleshooting and recovery diagnostics."""
        config: RunnableConfig = {"configurable": {"thread_id": case_id}}
        snapshot = self.graph.get_state(config)
        return cast(InvestigationState, dict(snapshot.values))

    def close(self) -> None:
        """Release the local checkpoint database connection on application shutdown."""
        self._checkpoint_connection.close()

    def validate_alert(self, state: InvestigationState) -> InvestigationState:
        self._report_progress("validate_alert")
        try:
            alert = self.gateway.get_alert(state["case_id"])
        except CopilotError as error:
            return {"errors": [*state.get("errors", []), str(error)]}
        return {"alert": alert}

    def collect_evidence(self, state: InvestigationState) -> InvestigationState:
        self._report_progress("collect_evidence")
        if "alert" not in state:
            return self._failed_packet(
                state, "evidence_agent", "Alert validation failed; no data was queried."
            )
        alert = state["alert"]
        try:
            profile = self.gateway.get_account_profile(alert.account_id)
            alerted_transaction = self.gateway.get_transaction(alert.transaction_id)
            transactions = self.gateway.get_recent_transactions(alert.account_id)
        except CopilotError as error:
            return self._failed_packet(state, "evidence_agent", str(error))

        evidence = [
            EvidenceItem(
                evidence_id=f"transaction:{alerted_transaction.transaction_id}",
                source_type="transaction",
                source_reference=alerted_transaction.transaction_id,
                finding=(
                    f"Alerted outbound payment was AUD {alerted_transaction.amount_aud:,.0f} via "
                    f"{alerted_transaction.payment_rail}."
                ),
                confidence=1.0,
            ),
            EvidenceItem(
                evidence_id=f"account:{profile.account_id}:baseline",
                source_type="account",
                source_reference=profile.account_id,
                finding=(
                    "Usual outbound payment maximum is AUD "
                    f"{profile.usual_outbound_payment_max_aud:,.0f}."
                ),
                confidence=1.0,
            ),
            EvidenceItem(
                evidence_id=f"transaction:{alerted_transaction.transaction_id}:payee",
                source_type="transaction",
                source_reference=alerted_transaction.transaction_id,
                finding=f"Payee is first-time={alerted_transaction.first_time_counterparty}.",
                confidence=1.0,
            ),
        ]
        findings = [item.finding for item in evidence]
        prior_inbound = [
            transaction
            for transaction in transactions
            if transaction.direction == "inbound"
            and transaction.occurred_at < alerted_transaction.occurred_at
        ]
        if prior_inbound:
            latest = prior_inbound[-1]
            if (alerted_transaction.occurred_at - latest.occurred_at).total_seconds() <= 3600:
                item = EvidenceItem(
                    evidence_id=f"transaction:{latest.transaction_id}:related_credit",
                    source_type="transaction",
                    source_reference=latest.transaction_id,
                    finding=(
                        "A recent inbound credit of AUD "
                        f"{latest.amount_aud:,.0f} occurred before the "
                        "alerted payment."
                    ),
                    confidence=0.95,
                )
                evidence.append(item)
                findings.append(item.finding)
        limitations: list[str] = []
        if not alert.reason:
            limitations.append("Alert reason was missing.")
        packet = AgentPacket(
            case_id=alert.case_id,
            agent_name="evidence_agent",
            status="complete",
            findings=findings,
            evidence=evidence,
            limitations=limitations,
            confidence=0.9 if not limitations else 0.65,
            recommended_next_step="retrieve applicable approved policy",
        )
        return {"evidence_packet": packet}

    def retrieve_policy(self, state: InvestigationState) -> InvestigationState:
        self._report_progress("retrieve_policy")
        alert = state.get("alert")
        evidence = state.get("evidence_packet")
        if alert is None or evidence is None:
            return self._failed_packet(
                state, "policy_agent", "Required alert or evidence context was unavailable."
            )
        if state.get("control_mode") == "policy_source_unavailable":
            # Demo-only fault injection for the Streamlit safe-failure walkthrough.
            # Normal analyst routes never set this state field.
            return self._failed_packet(
                state,
                "policy_agent",
                "Approved-policy source was unavailable after bounded retry and fallback checks.",
            )
        query = " ".join([alert.reason, *evidence.findings])
        try:
            # Four focused procedures give the analyst useful policy breadth without
            # overwhelming the synthesis context or hiding the most relevant source.
            retrieval = self.retriever.retrieve_with_assessment(query, top_k=4)
        except Exception as error:
            # A backend that cannot provide its own safe fallback must never cause
            # the graph to produce an ungoverned recommendation.
            return self._failed_packet(
                state, "policy_agent", f"Approved-policy retrieval was unavailable: {error}"
            )
        citations = retrieval.citations
        packet = AgentPacket(
            case_id=alert.case_id,
            agent_name="policy_agent",
            status="complete" if citations else "partial",
            findings=["Retrieved approved procedure context for the investigation draft."],
            citations=citations,
            limitations=[] if citations else ["No approved policy content was retrieved."],
            confidence=retrieval.assessment.confidence,
            recommended_next_step="synthesise evidence-backed case draft",
        )
        return {"policy_packet": packet, "retrieval_assessment": retrieval.assessment}

    def assess_answerability(self, state: InvestigationState) -> InvestigationState:
        self._report_progress("assess_answerability")
        policy = state.get("policy_packet")
        gate = evaluate_policy_answerability(
            state.get("evidence_packet"),
            state.get("retrieval_assessment"),
            len(policy.citations) if policy else 0,
        )
        if metrics_enabled.get():
            ANSWERABILITY_GATES.labels(outcome="pass" if gate.passed else "fail").inc()
        return {"answerability_gate": gate}

    @staticmethod
    def route_after_answerability(
        state: InvestigationState,
    ) -> Literal["synthesise_case", "insufficient_evidence"]:
        gate = state.get("answerability_gate")
        return "synthesise_case" if gate is not None and gate.passed else "insufficient_evidence"

    def synthesise_case(self, state: InvestigationState) -> InvestigationState:
        self._report_progress("synthesise_case")
        alert = state.get("alert")
        evidence = state.get("evidence_packet")
        policy = state.get("policy_packet")
        if alert is None or evidence is None or policy is None:
            return {
                "errors": [*state.get("errors", []), "Synthesis prerequisites were unavailable."]
            }
        confidence = min(evidence.confidence, policy.confidence)
        confidence_band = self._confidence_band(confidence)
        confidence_rationale = [
            f"Evidence confidence: {evidence.confidence:.2f}.",
            f"Approved-policy retrieval confidence: {policy.confidence:.2f}.",
            "Combined confidence uses the weaker component.",
        ]
        recommendation = Recommendation.FURTHER_INVESTIGATION
        if evidence.status != "complete" or not policy.citations or confidence < 0.6:
            recommendation = Recommendation.INSUFFICIENT_EVIDENCE
        elif alert.severity == "high":
            recommendation = Recommendation.HUMAN_ESCALATION
        draft = InvestigationDraft(
            case_id=alert.case_id,
            summary=(
                "A synthetic unusual outbound-payment alert was assessed using account context, "
                "transaction evidence, and approved procedure content. "
                "Human analyst review is required."
            ),
            observed_signals=evidence.findings,
            evidence_ids=[item.evidence_id for item in evidence.evidence],
            policy_citations=policy.citations,
            limitations=[
                *evidence.limitations,
                *policy.limitations,
                *(
                    ["Confidence is moderate; analyst should obtain or verify further evidence."]
                    if confidence_band == ConfidenceBand.MODERATE
                    else []
                ),
            ],
            recommendation=recommendation,
            confidence=confidence,
            confidence_band=confidence_band,
            confidence_rationale=confidence_rationale,
        )
        if self.draft_generator is not None:
            deterministic_draft = draft
            model_started_at = perf_counter()
            try:
                draft = self.draft_generator.generate(draft)
                generation_gate = evaluate_generated_summary(draft.summary, deterministic_draft)
                if not generation_gate.passed:
                    MODEL_DRAFTS.labels(outcome="generation_guardrail_fallback").inc()
                    MODEL_DRAFT_DURATION.observe(perf_counter() - model_started_at)
                    deterministic_draft.limitations.append(
                        "Generated summary was rejected by the grounding gate; deterministic "
                        "summary was used."
                    )
                    return {
                        "draft": deterministic_draft,
                        "generation_gate": generation_gate,
                        "errors": [
                            *state.get("errors", []),
                            "Generation grounding fallback: " + "; ".join(generation_gate.reasons),
                        ],
                    }
                MODEL_DRAFTS.labels(outcome="success").inc()
                MODEL_DRAFT_DURATION.observe(perf_counter() - model_started_at)
                return {"draft": draft, "generation_gate": generation_gate}
            except Exception as error:  # Provider failure must never bypass human review.
                MODEL_DRAFTS.labels(outcome="fallback").inc()
                MODEL_DRAFT_DURATION.observe(perf_counter() - model_started_at)
                draft.limitations.append(
                    "Live model drafting was unavailable; deterministic fallback was used."
                )
                return {
                    "draft": draft,
                    "generation_gate": GateResult(
                        gate_name="generation_groundedness",
                        passed=False,
                        reasons=[
                            "Live generation was unavailable; deterministic summary was retained."
                        ],
                    ),
                    "errors": [*state.get("errors", []), f"Model fallback: {error}"],
                }
        return {"draft": draft}

    def run_gates(self, state: InvestigationState) -> InvestigationState:
        self._report_progress("run_gates")
        draft = state.get("draft")
        if draft is None:
            result = GateResult(
                gate_name="draft_available",
                passed=False,
                reasons=["No draft was available for validation."],
            )
            return {"gate_results": [result]}
        return {"gate_results": evaluate_draft(draft)}

    @staticmethod
    def route_after_gates(
        state: InvestigationState,
    ) -> Literal["human_review", "insufficient_evidence"]:
        draft = state.get("draft")
        gates = state.get("gate_results", [])
        if draft is None or draft.recommendation == Recommendation.INSUFFICIENT_EVIDENCE:
            return "insufficient_evidence"
        return "human_review" if all(gate.passed for gate in gates) else "insufficient_evidence"

    def prepare_human_review(self, state: InvestigationState) -> InvestigationState:
        self._report_progress("prepare_human_review")
        return {"route": "human_review"}

    def mark_insufficient_evidence(self, state: InvestigationState) -> InvestigationState:
        self._report_progress("mark_insufficient_evidence")
        return {"route": "insufficient_evidence"}

    @staticmethod
    def _report_progress(node_name: str) -> None:
        callback = workflow_progress_callback.get()
        if callback is not None:
            callback(node_name)

    @staticmethod
    def _failed_packet(
        state: InvestigationState,
        agent_name: Literal["evidence_agent", "policy_agent", "synthesis_agent"],
        reason: str,
    ) -> InvestigationState:
        packet = AgentPacket(
            case_id=state["case_id"],
            agent_name=agent_name,
            status="failed",
            limitations=[reason],
            confidence=0.0,
            recommended_next_step="route to human review as insufficient evidence",
        )
        if agent_name == "evidence_agent":
            return {"evidence_packet": packet, "errors": [*state.get("errors", []), reason]}
        return {"policy_packet": packet, "errors": [*state.get("errors", []), reason]}

    @staticmethod
    def _confidence_band(confidence: float) -> ConfidenceBand:
        if confidence >= 0.8:
            return ConfidenceBand.HIGH
        if confidence >= 0.6:
            return ConfidenceBand.MODERATE
        return ConfidenceBand.LOW
