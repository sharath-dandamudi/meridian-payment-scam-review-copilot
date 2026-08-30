"""Prometheus-compatible runtime metrics for operational monitoring."""

from contextvars import ContextVar

from prometheus_client import Counter, Histogram

metrics_enabled: ContextVar[bool] = ContextVar("metrics_enabled", default=True)

WORKFLOWS = Counter(
    "copilot_workflows_total",
    "Completed investigation workflows by route.",
    ["route"],
)
GATE_FAILURES = Counter(
    "copilot_gate_failures_total",
    "Failed deterministic gates by name.",
    ["gate_name"],
)
WORKFLOW_DURATION = Histogram(
    "copilot_workflow_duration_seconds",
    "End-to-end workflow duration.",
)
MCP_TOOL_CALLS = Counter(
    "copilot_mcp_tool_calls_total",
    "Read-only MCP gateway calls by tool and outcome.",
    ["tool_name", "outcome"],
)
MCP_TOOL_DURATION = Histogram(
    "copilot_mcp_tool_duration_seconds",
    "Read-only MCP gateway call duration by tool.",
    ["tool_name"],
)
RAG_RETRIEVALS = Counter(
    "copilot_rag_retrievals_total",
    "Policy retrievals by deterministic confidence band.",
    ["confidence_band"],
)
RAG_RETRIEVAL_SCORE = Histogram(
    "copilot_rag_top_keyword_score",
    "Top keyword-overlap score from policy retrieval.",
)
RAG_RETRIEVAL_DURATION = Histogram(
    "copilot_rag_retrieval_duration_seconds",
    "Policy retrieval duration.",
)
RAG_FALLBACKS = Counter(
    "copilot_rag_fallbacks_total",
    "Hosted policy retrieval fallbacks by safe fallback reason.",
    ["reason"],
)
RERANKER_RUNS = Counter(
    "copilot_reranker_runs_total",
    "Cross-encoder reranking attempts by outcome.",
    ["outcome"],
)
RERANKER_DURATION = Histogram(
    "copilot_reranker_duration_seconds",
    "Cross-encoder reranking duration.",
)
MODEL_DRAFTS = Counter(
    "copilot_model_drafts_total",
    "Structured drafting attempts by outcome.",
    ["outcome"],
)
MODEL_DRAFT_DURATION = Histogram(
    "copilot_model_draft_duration_seconds",
    "Live structured model drafting duration.",
)
MODEL_TOKENS = Counter(
    "copilot_model_tokens_total",
    "Model tokens consumed by token type.",
    ["token_type"],
)
MODEL_ESTIMATED_COST_USD = Counter(
    "copilot_model_estimated_cost_usd_total",
    "Estimated model cost based on explicitly configured provider rates.",
)
ANSWERABILITY_GATES = Counter(
    "copilot_answerability_gates_total",
    "Policy answerability gate decisions by outcome.",
    ["outcome"],
)
CACHE_EVENTS = Counter(
    "copilot_cache_events_total",
    "In-process cache events by cache name and outcome.",
    ["cache_name", "outcome"],
)
