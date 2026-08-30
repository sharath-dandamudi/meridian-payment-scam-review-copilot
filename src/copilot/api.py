"""FastAPI boundary for the analyst UI and operational checks."""

from __future__ import annotations

import json
import os
import queue
import threading
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from copilot.case_store import CaseStore
from copilot.conversation import (
    ConversationRequest,
    conversation_responder_from_settings,
    respond_to_case_question,
)
from copilot.conversation_evaluation import evaluate_conversations
from copilot.drafting import draft_generator_from_settings
from copilot.evaluation import evaluate_golden_cases
from copilot.evaluation_experiments import EvaluationExperimentStore, snapshot_from_reports
from copilot.feedback import publish_analyst_feedback
from copilot.generation_evaluation import NebiusGroundednessJudge
from copilot.intake import classify_intent
from copilot.models import AnalystDecision
from copilot.observability import configure_logging, request_id_context
from copilot.pinecone_policy import PineconePolicyRetriever
from copilot.rag_evaluation import evaluate_policy_retrieval
from copilot.retrieval import PolicyRetriever
from copilot.safety_evaluation import evaluate_safety_cases
from copilot.security import InMemoryRateLimiter, require_role
from copilot.settings import Settings
from copilot.workflow import InvestigationState, InvestigationWorkflow

PROGRESS_STAGES: dict[str, tuple[int, str]] = {
    "validate_alert": (1, "Validating the selected alert"),
    "collect_evidence": (2, "Collecting read-only case evidence"),
    "retrieve_policy": (3, "Retrieving and reranking approved policy"),
    "assess_answerability": (4, "Checking whether policy evidence is sufficient"),
    "synthesise_case": (5, "Preparing the evidence-backed review brief"),
    "run_gates": (6, "Applying grounding and safety controls"),
    "prepare_human_review": (7, "Preparing the analyst review package"),
    "mark_insufficient_evidence": (7, "Routing safely to insufficient evidence"),
}
PROGRESS_STAGE_COUNT = 7


def _root_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _configure_langsmith(settings: Settings) -> None:
    if settings.langsmith_tracing:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
        if settings.langsmith_api_key is not None:
            os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key.get_secret_value()


def _serialise_state(state: InvestigationState) -> dict[str, Any]:
    return {
        "case_id": state["case_id"],
        "trace_id": state.get("trace_id"),
        "route": state.get("route"),
        "draft": state["draft"].model_dump(mode="json") if state.get("draft") else None,
        "retrieval_assessment": (
            state["retrieval_assessment"].model_dump(mode="json")
            if state.get("retrieval_assessment")
            else None
        ),
        "answerability_gate": (
            state["answerability_gate"].model_dump(mode="json")
            if state.get("answerability_gate")
            else None
        ),
        "gates": [gate.model_dump(mode="json") for gate in state.get("gate_results", [])],
        "generation_gate": (
            state["generation_gate"].model_dump(mode="json")
            if state.get("generation_gate")
            else None
        ),
        "errors": state.get("errors", []),
    }


def _policy_retriever(settings: Settings, policy_dir: Path) -> PineconePolicyRetriever | None:
    if settings.rag_backend.lower() != "pinecone":
        return None
    try:
        return PineconePolicyRetriever(settings, policy_dir)
    except Exception:
        return None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    root = _root_dir()
    _configure_langsmith(settings)
    configure_logging()
    workflow = InvestigationWorkflow(
        root / settings.fixtures_dir,
        root / settings.policy_dir,
        root / "artifacts" / "workflow_checkpoints.sqlite",
        draft_generator_from_settings(settings),
        _policy_retriever(settings, root / settings.policy_dir),
    )
    hosted_rag_active = settings.rag_backend.lower() != "pinecone" or isinstance(
        workflow.retriever, PineconePolicyRetriever
    )
    case_store = CaseStore(root / "artifacts" / "cases.sqlite")
    experiment_store = EvaluationExperimentStore(root / "artifacts" / "evaluation_baselines.json")
    conversation_responder = conversation_responder_from_settings(settings)
    app = FastAPI(
        title="Meridian — Payment Scam Review Copilot",
        version="0.1.0",
        description="Governed, synthetic-data-only payment-scam review workflow.",
    )
    allowed_origins = [
        origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
    )
    rate_limiter = InMemoryRateLimiter(settings.rate_limit_per_minute)

    @app.middleware("http")
    async def protect_and_correlate(request: Request, call_next: Any) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        request_id_context.set(request_id)
        content_length = int(request.headers.get("content-length", "0"))
        if content_length > settings.max_request_bytes:
            return JSONResponse(
                status_code=413, content={"detail": "Request body exceeds the allowed size."}
            )
        client_key = request.headers.get("X-API-Key") or (
            request.client.host if request.client else "unknown"
        )
        if request.url.path not in {"/health", "/ready"} and not rate_limiter.allow(client_key):
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded."})
        response = cast(Response, await call_next(request))
        response.headers["X-Request-ID"] = request_id
        return response

    analyst_access = require_role(settings, "analyst", "operations")
    operations_access = require_role(settings, "operations")

    def offline_release_reports() -> tuple[Any, Any, Any, Any]:
        """Run local, deterministic release suites without spending model credits."""
        golden_workflow = InvestigationWorkflow(
            root / settings.fixtures_dir,
            root / settings.policy_dir,
            root / "artifacts" / "evaluation_checkpoints.sqlite",
        )
        conversation_workflow = InvestigationWorkflow(
            root / settings.fixtures_dir,
            root / settings.policy_dir,
            root / "artifacts" / "conversation_evaluation_checkpoints.sqlite",
        )
        safety_workflow = InvestigationWorkflow(
            root / settings.fixtures_dir,
            root / settings.policy_dir,
            root / "artifacts" / "safety_evaluation_checkpoints.sqlite",
        )
        try:
            golden = evaluate_golden_cases(
                golden_workflow, root / "evals" / "golden" / "cases.json"
            )
            rag = evaluate_policy_retrieval(
                PolicyRetriever(root / settings.policy_dir), root / "evals" / "rag" / "queries.json"
            )
            conversation = evaluate_conversations(
                conversation_workflow,
                CaseStore(root / "artifacts" / "conversation_evaluation.sqlite"),
                root / "evals" / "conversation" / "cases.json",
            )
            safety = evaluate_safety_cases(
                safety_workflow,
                CaseStore(root / "artifacts" / "safety_evaluation.sqlite"),
                root / "evals" / "safety" / "cases.json",
            )
            return golden, rag, conversation, safety
        finally:
            golden_workflow.close()
            conversation_workflow.close()
            safety_workflow.close()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "model_provider": settings.model_provider}

    @app.get("/ready")
    def ready() -> dict[str, str]:
        if not hosted_rag_active:
            raise HTTPException(
                status_code=503, detail="Hosted RAG was requested but is unavailable."
            )
        return {
            "status": "ready",
            "model_mode": "live" if settings.live_model_enabled else "deterministic",
            "rag_backend": settings.rag_backend,
        }

    @app.post("/intake")
    def intake(request: dict[str, str], _: str = Depends(analyst_access)) -> dict[str, Any]:
        user_request = request.get("request", "")
        return classify_intent(user_request).model_dump(mode="json")

    @app.get("/cases")
    def list_cases(_: str = Depends(analyst_access)) -> list[dict[str, str]]:
        return [
            {
                "case_id": alert.case_id,
                # Keep the queue label compact. The full reason is shown in the analyst
                # workspace after selection, where it is readable and actionable.
                "label": f"{alert.case_id} · {alert.severity.title()}",
                "severity": alert.severity,
                "reason": alert.reason,
            }
            for alert in workflow.gateway.list_alerts()
        ]

    @app.post("/cases/{case_id}/investigate")
    def investigate(case_id: str, _: str = Depends(analyst_access)) -> dict[str, Any]:
        state = workflow.invoke(case_id)
        if not state.get("draft") and not state.get("errors"):
            raise HTTPException(
                status_code=500, detail="Workflow produced no draft or failure information."
            )
        response = _serialise_state(state)
        case_store.record_investigation(
            case_id,
            response["route"] or "insufficient_evidence",
            state.get("draft"),
            state.get("trace_id"),
        )
        return response

    @app.post("/cases/{case_id}/investigate/stream")
    def investigate_stream(
        case_id: str,
        control_mode: Literal["policy_source_unavailable"] | None = None,
        _: str = Depends(analyst_access),
    ) -> StreamingResponse:
        """Stream real, safe node-start events followed by the normal investigation result."""
        request_id = request_id_context.get()

        def event_stream() -> Any:
            events: queue.Queue[dict[str, Any] | None] = queue.Queue()

            def report(node_name: str) -> None:
                position, message = PROGRESS_STAGES[node_name]
                events.put(
                    {
                        "type": "stage",
                        "node": node_name,
                        "position": position,
                        "total": PROGRESS_STAGE_COUNT,
                        "message": message,
                    }
                )

            def run_workflow() -> None:
                request_token = request_id_context.set(request_id)
                try:
                    state = workflow.invoke(
                        case_id, progress_callback=report, control_mode=control_mode
                    )
                    if not state.get("draft") and not state.get("errors"):
                        events.put(
                            {
                                "type": "error",
                                "message": (
                                    "The workflow completed without a review brief "
                                    "or safe failure reason."
                                ),
                            }
                        )
                    else:
                        response = _serialise_state(state)
                        case_store.record_investigation(
                            case_id,
                            response["route"] or "insufficient_evidence",
                            state.get("draft"),
                            state.get("trace_id"),
                        )
                        events.put({"type": "result", "result": response})
                except Exception:
                    # Do not put raw backend exceptions into a browser response.
                    events.put(
                        {
                            "type": "error",
                            "message": (
                                "The investigation could not complete. "
                                "Check the request trace and API logs."
                            ),
                        }
                    )
                finally:
                    request_id_context.reset(request_token)
                    events.put(None)

            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "stage",
                        "node": "start",
                        "position": 0,
                        "total": PROGRESS_STAGE_COUNT,
                        "message": "Starting governed investigation",
                    }
                )
                + "\n\n"
            )
            threading.Thread(target=run_workflow, daemon=True).start()
            while True:
                event = events.get()
                if event is None:
                    break
                yield "data: " + json.dumps(event) + "\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/cases/{case_id}/review")
    def record_review(
        case_id: str, decision: AnalystDecision, _: str = Depends(analyst_access)
    ) -> dict[str, str]:
        if decision.case_id != case_id:
            raise HTTPException(status_code=400, detail="Path and decision case IDs must match.")
        case_store.record_analyst_decision(decision)
        try:
            feedback_published = publish_analyst_feedback(
                settings, case_store.trace_id_for_case(case_id), decision
            )
        except Exception:
            feedback_published = False
        return {
            "status": "recorded",
            "case_id": case_id,
            "langsmith_feedback_published": str(feedback_published).lower(),
        }

    @app.get("/cases/{case_id}/review")
    def get_latest_review(case_id: str, _: str = Depends(analyst_access)) -> dict[str, str] | None:
        return case_store.latest_decision(case_id)

    @app.get("/cases/{case_id}/chat")
    def conversation_history(
        case_id: str, _: str = Depends(analyst_access)
    ) -> list[dict[str, str]]:
        return case_store.recent_conversation(case_id)

    @app.post("/cases/{case_id}/chat")
    def chat_about_case(
        case_id: str,
        request: ConversationRequest,
        _: str = Depends(analyst_access),
    ) -> dict[str, object]:
        state = workflow.latest_checkpoint(case_id)
        draft = state.get("draft")
        evidence = state.get("evidence_packet")
        if draft is None or evidence is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Investigate the case successfully before asking Meridian follow-up questions."
                ),
            )
        retrieval_query = " ".join([request.question, *draft.observed_signals])
        retrieval = workflow.retriever.retrieve_with_assessment(retrieval_query, top_k=4)
        return respond_to_case_question(
            case_id,
            request.question,
            draft,
            retrieval,
            case_store,
            conversation_responder,
        ).model_dump()

    @app.get("/review-metrics")
    def review_metrics(
        _: str = Depends(operations_access),
    ) -> dict[str, dict[str, int] | dict[str, int | float]]:
        return {
            "decisions": case_store.decision_counts(),
            "online_evaluation": case_store.online_evaluation_summary(),
            "escalation_agreement": case_store.escalation_agreement_summary(),
        }

    @app.get("/evals/golden")
    def golden_evaluation(_: str = Depends(operations_access)) -> dict[str, Any]:
        # Golden release tests must be repeatable and must not consume live-model
        # credits. They intentionally use the deterministic local RAG baseline.
        evaluation_workflow = InvestigationWorkflow(
            root / settings.fixtures_dir,
            root / settings.policy_dir,
            root / "artifacts" / "evaluation_checkpoints.sqlite",
        )
        report = evaluate_golden_cases(
            evaluation_workflow, root / "evals" / "golden" / "cases.json"
        )
        evaluation_workflow.close()
        return {
            "passed": report.passed,
            "pass_rate": report.pass_rate,
            "summary": report.summary,
            "cases": [case.__dict__ for case in report.cases],
        }

    @app.get("/evals/rag")
    def rag_evaluation(_: str = Depends(operations_access)) -> dict[str, Any]:
        # This release gate uses the deterministic local corpus to make changes
        # reproducible. Hosted Pinecone is compared in a separate experiment.
        report = evaluate_policy_retrieval(
            PolicyRetriever(root / settings.policy_dir), root / "evals" / "rag" / "queries.json"
        )
        return {
            "passed": report.passed,
            "pass_rate": report.pass_rate,
            "cases": [case.__dict__ for case in report.cases],
        }

    @app.get("/evals/conversation")
    def conversation_evaluation(_: str = Depends(operations_access)) -> dict[str, object]:
        evaluation_store = CaseStore(root / "artifacts" / "conversation_evaluation.sqlite")
        evaluation_workflow = InvestigationWorkflow(
            root / settings.fixtures_dir,
            root / settings.policy_dir,
            root / "artifacts" / "conversation_evaluation_checkpoints.sqlite",
        )
        report = evaluate_conversations(
            evaluation_workflow,
            evaluation_store,
            root / "evals" / "conversation" / "cases.json",
        )
        evaluation_workflow.close()
        return {
            "passed": report.passed,
            "pass_rate": report.pass_rate,
            "cases": [case.__dict__ for case in report.cases],
        }

    @app.get("/evals/safety")
    def safety_evaluation(_: str = Depends(operations_access)) -> dict[str, Any]:
        evaluation_workflow = InvestigationWorkflow(
            root / settings.fixtures_dir,
            root / settings.policy_dir,
            root / "artifacts" / "safety_evaluation_checkpoints.sqlite",
        )
        try:
            report = evaluate_safety_cases(
                evaluation_workflow,
                CaseStore(root / "artifacts" / "safety_evaluation.sqlite"),
                root / "evals" / "safety" / "cases.json",
            )
        finally:
            evaluation_workflow.close()
        return {
            "passed": report.passed,
            "pass_rate": report.pass_rate,
            "summary": report.summary,
            "cases": [case.__dict__ for case in report.cases],
        }

    @app.get("/evals/experiments")
    def evaluation_experiments(_: str = Depends(operations_access)) -> dict[str, object]:
        golden, rag, conversation, safety = offline_release_reports()
        snapshot = snapshot_from_reports(golden, rag, conversation, safety)
        return {"current": snapshot.metrics, "comparisons": experiment_store.compare(snapshot)}

    @app.post("/evals/experiments/baselines/{name}")
    def save_evaluation_baseline(
        name: str, _: str = Depends(operations_access)
    ) -> dict[str, object]:
        golden, rag, conversation, safety = offline_release_reports()
        snapshot = snapshot_from_reports(golden, rag, conversation, safety)
        try:
            baseline = experiment_store.save_baseline(
                name,
                snapshot,
                {"workflow_version": app.version, "evaluation_mode": "deterministic-local"},
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"baseline": baseline, "comparisons": experiment_store.compare(snapshot)}

    @app.post("/evals/generation-judge/{case_id}")
    def generation_judge(case_id: str, _: str = Depends(operations_access)) -> dict[str, object]:
        """Explicit, offline LLM-as-judge check; never part of production routing."""
        if not settings.live_model_enabled or settings.nebius_api_key is None:
            raise HTTPException(
                status_code=409,
                detail="Enable the Nebius model before running a paid offline judge evaluation.",
            )
        state = workflow.invoke(case_id, record_metrics=False)
        draft = state.get("draft")
        if draft is None:
            raise HTTPException(status_code=422, detail="No draft was available to evaluate.")
        return NebiusGroundednessJudge(settings).evaluate(draft).model_dump()

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics(_: str = Depends(operations_access)) -> PlainTextResponse:
        return PlainTextResponse(generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
