"""Focused Streamlit analyst workspace for local demonstration."""
# ruff: noqa: E501

from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime
from typing import Any

import requests
import streamlit as st
from prometheus_client.parser import text_string_to_metric_families

API_URL = os.getenv("COPILOT_API_URL", "http://localhost:8000")
API_KEY = os.getenv("COPILOT_API_KEY")


def _api_headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY} if API_KEY else {}


def _metric_samples() -> list[tuple[str, float, dict[str, str]]]:
    response = requests.get(f"{API_URL}/metrics", headers=_api_headers(), timeout=3)
    response.raise_for_status()
    samples: list[tuple[str, float, dict[str, str]]] = []
    for family in text_string_to_metric_families(response.text):
        for sample in family.samples:
            samples.append((sample.name, float(sample.value), dict(sample.labels)))
    return samples


def _value(
    samples: list[tuple[str, float, dict[str, str]]],
    name: str,
    labels: dict[str, str] | None = None,
) -> float:
    return sum(
        value
        for sample_name, value, sample_labels in samples
        if sample_name == name and (labels is None or sample_labels == labels)
    )


def _labelled_rows(
    samples: list[tuple[str, float, dict[str, str]]], name: str
) -> list[dict[str, str | float]]:
    return [
        {**labels, "value": value} for sample_name, value, labels in samples if sample_name == name
    ]


def _health_label(value: float | None, good: float, watch: float) -> tuple[str, str]:
    """Return a small, explicit status rather than leaving metrics uninterpreted."""
    if value is None:
        return "No data yet", "neutral"
    if value >= good:
        return "Healthy", "good"
    if value >= watch:
        return "Watch", "watch"
    return "Needs attention", "bad"


def _status_card(title: str, value: str, explanation: str, tone: str, tooltip: str) -> None:
    st.markdown(
        f"""<div class="status-card {tone}">
        <span>{html.escape(title)} {_tooltip_icon(tooltip)}</span>
        <strong>{html.escape(value)}</strong>
        <small>{html.escape(explanation)}</small></div>""",
        unsafe_allow_html=True,
    )


def _section_heading(title: str, help_text: str) -> None:
    """Render a heading with a compact, inline explanation affordance."""
    st.markdown(
        f'<h3 class="section-heading">{html.escape(title)} {_tooltip_icon(help_text)}</h3>',
        unsafe_allow_html=True,
    )


def _tooltip_icon(explanation: str) -> str:
    """Return a compact hover/focus tooltip that stays within the visual hierarchy."""
    return (
        '<span class="inline-tooltip" tabindex="0">ⓘ'
        f'<span class="tooltip-content">{html.escape(explanation)}</span></span>'
    )


def _metric_help(container: Any, label: str, value: str | int, explanation: str) -> None:
    """Render a visually consistent metric with a compact inline tooltip."""
    container.markdown(
        f"""<div class="metric-card">
        <span class="metric-label">{html.escape(label)} {_tooltip_icon(explanation)}</span>
        <strong>{html.escape(str(value))}</strong></div>""",
        unsafe_allow_html=True,
    )


def _highlight_keywords(text: str) -> str:
    """Surface risk terms without changing the evidence itself."""
    escaped = html.escape(text)
    keywords = (
        "remote access",
        "first-time",
        "first time",
        "PayID",
        "overseas",
        "international",
        "unusual",
        "urgent",
        "high-value",
        "high value",
        "cryptocurrency",
        "mule",
        "scam",
        "new beneficiary",
    )
    pattern = "(" + "|".join(re.escape(keyword) for keyword in keywords) + ")"
    return re.sub(pattern, r"<mark>\1</mark>", escaped, flags=re.IGNORECASE)


def _highlight_retrieved_passage(excerpt: str, signals: list[str]) -> str:
    """Mark the sentence in a verbatim policy excerpt that matches case-specific terms."""
    anchors = {
        "remote access",
        "impersonation",
        "technical-support",
        "first-time payee",
        "first-time-payee",
        "new payee",
        "new beneficiary",
        "payid",
        "investment",
        "invoice",
        "supplier",
        "inbound credit",
        "rapid onward transfer",
        "mule-account",
        "overseas",
        "international",
        "cryptocurrency",
        "payment rail",
        "channel",
        "data gap",
    }
    ignored_words = {
        "account",
        "activity",
        "alerted",
        "analyst",
        "amount",
        "customer",
        "evidence",
        "investigation",
        "outbound",
        "payment",
        "review",
        "transaction",
        "unusual",
    }
    for signal in signals:
        anchors.update(
            word.lower()
            for word in re.findall(r"[A-Za-z][A-Za-z-]{4,}", signal)
            if word.lower() not in ignored_words
        )
    sentences = re.split(r"(?<=[.!?])\s+", excerpt.strip())
    matched = [any(anchor in sentence.lower() for anchor in anchors) for sentence in sentences]
    # A citation is already a selected source passage. When exact token overlap is not
    # available, highlight that passage rather than inventing a more specific link.
    if sentences and not any(matched):
        matched[0] = True
    rendered: list[str] = []
    for sentence, is_match in zip(sentences, matched, strict=True):
        safe_sentence = _highlight_keywords(sentence)
        if is_match:
            rendered.append(f'<span class="source-match">{safe_sentence}</span>')
        else:
            rendered.append(safe_sentence)
    return " ".join(rendered)


def _stream_investigation(
    case_id: str, control_mode: str | None = None
) -> dict[str, object] | None:
    """Render genuine server-side workflow progress from the SSE investigation endpoint."""
    progress = st.progress(0, text="Starting governed investigation…")
    result: dict[str, object] | None = None
    with st.status("Investigation in progress", expanded=True) as status:
        try:
            with requests.post(
                f"{API_URL}/cases/{case_id}/investigate/stream",
                headers=_api_headers(),
                timeout=60,
                stream=True,
                params={"control_mode": control_mode} if control_mode else None,
            ) as response:
                if not response.ok:
                    st.error(f"Could not prepare the brief: {response.text}")
                    status.update(label="Investigation could not start", state="error")
                    return None
                for raw_line in response.iter_lines():
                    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                    if not line or not line.startswith("data: "):
                        continue
                    event = json.loads(line.removeprefix("data: "))
                    if event["type"] == "stage":
                        position = int(event["position"])
                        total = int(event["total"])
                        message = str(event["message"])
                        progress.progress(
                            int(position / total * 100), text=f"Stage {position}/{total}: {message}"
                        )
                        status.update(label=f"Stage {position}/{total}: {message}", state="running")
                        if position:
                            status.write(f"{position}/{total} — {message}")
                    elif event["type"] == "result":
                        result = event["result"]
                    elif event["type"] == "error":
                        st.error(str(event["message"]))
                        status.update(label="Investigation could not complete", state="error")
        except (requests.RequestException, json.JSONDecodeError) as error:
            st.error(f"Could not prepare the brief: {error}")
            status.update(label="Investigation could not reach the backend", state="error")
            return None
        if result is None:
            status.update(label="Investigation could not complete", state="error")
            st.error("The backend did not return a review brief.")
            return None
        progress.progress(100, text="Review brief ready")
        status.update(label="Investigation complete", state="complete", expanded=False)
    return result


def _clear_selected_case_result() -> None:
    """Prevent a previous case or control-test result being read as the new alert's result."""
    st.session_state.pop("result", None)


@st.fragment(run_every="10s")
def _operations_dashboard() -> None:
    """Auto-refreshing, aggregate-only operating view for the local API."""
    try:
        samples = _metric_samples()
    except requests.RequestException:
        st.warning("Metrics endpoint is temporarily unavailable.")
        return

    workflow_count = _value(samples, "copilot_workflows_total")
    workflow_seconds = _value(samples, "copilot_workflow_duration_seconds_sum")
    workflow_duration_count = _value(samples, "copilot_workflow_duration_seconds_count")
    average_workflow_seconds = (
        workflow_seconds / workflow_duration_count if workflow_duration_count else 0.0
    )
    gate_failures = _value(samples, "copilot_gate_failures_total")
    model_fallbacks = _value(samples, "copilot_model_drafts_total", {"outcome": "fallback"})
    rag_fallbacks = _value(samples, "copilot_rag_fallbacks_total")

    mcp_successes = _value(samples, "copilot_mcp_tool_calls_total", {"outcome": "success"})
    mcp_successes += _value(samples, "copilot_mcp_tool_calls_total", {"outcome": "cache_hit"})
    mcp_errors = _value(samples, "copilot_mcp_tool_calls_total", {"outcome": "error"})
    mcp_rate = mcp_successes / (mcp_successes + mcp_errors) if mcp_successes + mcp_errors else None
    workflow_successes = _value(samples, "copilot_workflows_total", {"route": "human_review"})
    workflow_rate = workflow_successes / workflow_count if workflow_count else None
    fallback_count = model_fallbacks + rag_fallbacks
    fallback_rate = fallback_count / workflow_count if workflow_count else None

    _section_heading(
        "System status",
        "This is the first place to look. It turns the most important operating signals into a "
        "plain-English health assessment. Thresholds are demo guardrails, not production SLOs.",
    )
    overall_good = (
        workflow_rate is not None
        and workflow_rate >= 0.95
        and (mcp_rate is None or mcp_rate >= 0.99)
        and (fallback_rate is None or fallback_rate <= 0.05)
    )
    overall_watch = workflow_rate is None or (
        workflow_rate >= 0.85 and (mcp_rate is None or mcp_rate >= 0.95)
    )
    if workflow_count == 0 or mcp_rate is None:
        st.info(
            "Collecting baseline data — run a fresh investigation in this API process before "
            "treating gateway health as assessed. Restarting the local API resets these counters."
        )
    elif overall_good:
        st.success(
            "Operating normally — the workflow, gateway and fallback signals are within demo targets."
        )
    elif overall_watch:
        st.warning("Watch — there is not enough data yet or one reliability signal needs review.")
    else:
        st.error(
            "Needs attention — inspect the reliability and safety sections before relying on new results."
        )

    status_columns = st.columns(4)
    latency_tone = (
        "good"
        if average_workflow_seconds <= 15
        else "watch"
        if average_workflow_seconds <= 25
        else "bad"
    )
    _, workflow_tone = _health_label(workflow_rate, 0.95, 0.85)
    _, mcp_tone = _health_label(mcp_rate, 0.99, 0.95)
    fallback_value = "—" if fallback_rate is None else f"{fallback_rate:.0%}"
    fallback_tone = (
        "good"
        if fallback_rate is not None and fallback_rate <= 0.05
        else "watch"
        if fallback_rate is not None and fallback_rate <= 0.10
        else "neutral"
    )
    with status_columns[0]:
        _status_card(
            "Workflow completion",
            "—" if workflow_rate is None else f"{workflow_rate:.0%}",
            "Target ≥95%",
            workflow_tone,
            "Share of completed workflows that reached Human Review. It is a reliability measure, not scam accuracy.",
        )
    with status_columns[1]:
        _status_card(
            "MCP gateway",
            "—" if mcp_rate is None else f"{mcp_rate:.0%}",
            "Run a fresh brief to observe it" if mcp_rate is None else "Target ≥99% success",
            mcp_tone,
            "Success or cache-hit rate for read-only MCP evidence-tool calls. A dash means no calls in this API process.",
        )
    with status_columns[2]:
        _status_card(
            "Average investigation",
            f"{average_workflow_seconds:.1f}s" if workflow_duration_count else "—",
            "Green ≤15s; watch ≤25s",
            latency_tone if workflow_duration_count else "neutral",
            "Average end-to-end time for an investigation, including retrieval, reranking, drafting and gates.",
        )
    with status_columns[3]:
        _status_card(
            "Fallback rate",
            fallback_value,
            "Target ≤5% per investigation",
            fallback_tone,
            "Share of investigations where hosted RAG or live model drafting fell back to a safe local alternative.",
        )
    st.caption(
        f"{int(workflow_count)} investigations · {int(gate_failures)} safety-gate failures · "
        f"{int(model_fallbacks)} model fallbacks · {int(rag_fallbacks)} RAG fallbacks since API start."
    )

    st.markdown("#### Reliability")
    answerability_passes = _value(samples, "copilot_answerability_gates_total", {"outcome": "pass"})
    answerability_failures = _value(
        samples, "copilot_answerability_gates_total", {"outcome": "fail"}
    )
    reliability_columns = st.columns(3)
    _metric_help(
        reliability_columns[0],
        "Workflow completion",
        f"{workflow_rate:.0%}" if workflow_rate is not None else "—",
        "Share of completed investigations that reached the ordinary Human Review route. "
        "This is a workflow-reliability signal, not scam-detection accuracy. Target: at least 95%. "
        "A dash means no completed investigations in this API process.",
    )
    _metric_help(
        reliability_columns[1],
        "MCP success rate",
        f"{mcp_rate:.0%}" if mcp_rate is not None else "—",
        "Successful or cached read-only MCP gateway tool calls divided by all completed gateway calls. "
        "Target: at least 99%. A dash means this local API has not recorded an MCP call yet.",
    )
    _metric_help(
        reliability_columns[2],
        "Answerability pass rate",
        f"{answerability_passes / (answerability_passes + answerability_failures):.0%}"
        if answerability_passes + answerability_failures
        else "—",
        "Percentage of retrieval attempts with enough case evidence, at least two policy citations, "
        "and sufficient retrieval confidence to support a grounded brief. A sudden decline is a warning; "
        "a lower rate can be correct when questions are out of scope.",
    )

    cache_hits = _value(
        samples, "copilot_cache_events_total", {"cache_name": "mcp_gateway", "outcome": "hit"}
    ) + _value(
        samples, "copilot_cache_events_total", {"cache_name": "policy_rag", "outcome": "hit"}
    )
    cache_misses = _value(
        samples, "copilot_cache_events_total", {"cache_name": "mcp_gateway", "outcome": "miss"}
    ) + _value(
        samples, "copilot_cache_events_total", {"cache_name": "policy_rag", "outcome": "miss"}
    )
    st.caption(
        f"Read-only cache: {int(cache_hits)} hits / {int(cache_misses)} misses. "
        "ⓘ A cache hit reuses a recent read-only result; it improves latency without changing the decision."
    )

    _section_heading(
        "RAG quality",
        "High confidence means the retrieved approved policy strongly matched the query. Low confidence "
        "should route to insufficient evidence rather than letting a fluent answer hide uncertainty.",
    )
    rag_total = _value(samples, "copilot_rag_retrievals_total")
    rag_high = _value(samples, "copilot_rag_retrievals_total", {"confidence_band": "high"})
    rag_moderate = _value(samples, "copilot_rag_retrievals_total", {"confidence_band": "moderate"})
    rag_low = _value(samples, "copilot_rag_retrievals_total", {"confidence_band": "low"})
    rag_score_count = _value(samples, "copilot_rag_top_keyword_score_count")
    rag_score = _value(samples, "copilot_rag_top_keyword_score_sum")
    rag_duration_count = _value(samples, "copilot_rag_retrieval_duration_seconds_count")
    rag_duration = _value(samples, "copilot_rag_retrieval_duration_seconds_sum")
    rag_columns = st.columns(4)
    _metric_help(
        rag_columns[0],
        "Retrievals",
        int(rag_total),
        "Number of policy-retrieval attempts since the API started. It measures volume, not quality.",
    )
    _metric_help(
        rag_columns[1],
        "High confidence",
        int(rag_high),
        "Number of retrievals above Meridian's high-confidence threshold. This is not proof a payment "
        "is a scam; citations and analyst review remain required.",
    )
    _metric_help(
        rag_columns[2],
        "Moderate / low",
        f"{int(rag_moderate)} / {int(rag_low)}",
        "Moderate results may support a brief with analyst verification. Low results should normally fail "
        "the answerability gate and route safely to insufficient evidence.",
    )
    _metric_help(
        rag_columns[3],
        "Average retrieval score",
        f"{rag_score / rag_score_count:.1f}" if rag_score_count else "—",
        "A backend-specific diagnostic score from the best policy match. It is not a universal percentage, "
        "so there is no single good target. Judge retrieval using the answerability gate, offline recall "
        "and analyst feedback. A dash means no retrievals yet.",
    )
    st.caption(
        f"Average RAG retrieval time: {(rag_duration / rag_duration_count * 1000):.1f} ms"
        if rag_duration_count
        else "No RAG retrievals recorded yet."
    )

    left, right = st.columns(2)
    with left:
        st.markdown("#### MCP gateway health")
        with st.popover("ⓘ"):
            st.write(
                "Shows each read-only evidence tool and its success, error or cache-hit count. "
                "Errors should be investigated because missing evidence routes the workflow safely."
            )
        mcp_rows = _labelled_rows(samples, "copilot_mcp_tool_calls_total")
        if mcp_rows:
            st.dataframe(mcp_rows, use_container_width=True, hide_index=True)
        else:
            st.caption("No MCP gateway calls recorded yet.")
    with right:
        st.markdown("#### Model drafting")
        with st.popover("ⓘ"):
            st.write(
                "Measures the optional live-model narrative step. The model never decides the route, "
                "evidence, citations or analyst outcome."
            )
        model_successes = _value(samples, "copilot_model_drafts_total", {"outcome": "success"})
        model_seconds = _value(samples, "copilot_model_draft_duration_seconds_sum")
        model_count = _value(samples, "copilot_model_draft_duration_seconds_count")
        _metric_help(
            st,
            "Successful structured drafts",
            int(model_successes),
            "Number of live-model drafts that met the required Pydantic structure and passed the "
            "generation-grounding gate. It does not itself measure analyst usefulness.",
        )
        _metric_help(
            st,
            "Average model time",
            f"{model_seconds / model_count:.2f}s" if model_count else "—",
            "Average time spent in the live narrative-generation call only. It excludes most evidence "
            "and retrieval work, and is used for capacity and latency planning.",
        )
        input_tokens = _value(samples, "copilot_model_tokens_total", {"token_type": "input"})
        output_tokens = _value(samples, "copilot_model_tokens_total", {"token_type": "output"})
        estimated_cost = _value(samples, "copilot_model_estimated_cost_usd_total")
        st.caption(
            f"Tokens: {int(input_tokens):,} input / {int(output_tokens):,} output. "
            "ⓘ Token volume is a cost-capacity diagnostic, not a quality score."
        )
        st.caption(
            f"Estimated configured model cost: USD ${estimated_cost:.4f}. "
            "ⓘ This is only as accurate as the model-rate values configured locally."
        )
        st.caption("Fallbacks retain the deterministic draft and remain human-review only.")

    _section_heading(
        "Analyst feedback and online evaluation",
        "These measures learn from final human outcomes. Precision and recall here concern escalation "
        "agreement, not whether a customer is definitively a scam victim.",
    )
    try:
        review_metrics = requests.get(
            f"{API_URL}/review-metrics", headers=_api_headers(), timeout=3
        ).json()
        online_evaluation = review_metrics["online_evaluation"]
        feedback_columns = st.columns(3)
        _metric_help(
            feedback_columns[0],
            "Reviews",
            int(online_evaluation["review_count"]),
            "Number of analyst outcomes recorded. More labelled reviews make online evaluation more reliable.",
        )
        _metric_help(
            feedback_columns[1],
            "Draft usefulness rate",
            f"{online_evaluation['draft_usefulness_rate']:.0%}",
            "Share of reviewed drafts marked approved or edited, rather than sent back for more evidence. "
            "Interpret only after enough analyst reviews have accumulated.",
        )
        _metric_help(
            feedback_columns[2],
            "Escalations",
            int(online_evaluation["escalated_count"]),
            "Number of final analyst outcomes recorded as escalated. It is an outcome count, not a model error count.",
        )
        agreement = review_metrics["escalation_agreement"]
        agreement_columns = st.columns(2)
        _metric_help(
            agreement_columns[0],
            "Escalation precision",
            f"{agreement['escalation_precision']:.0%}" if agreement["labelled_case_count"] else "—",
            "Of drafts recommending escalation, the share that the analyst ultimately escalated. "
            "This measures agreement with analysts, not scam-detection precision.",
        )
        _metric_help(
            agreement_columns[1],
            "Escalation recall",
            f"{agreement['escalation_recall']:.0%}" if agreement["labelled_case_count"] else "—",
            "Of cases the analyst escalated, the share where Meridian recommended escalation. "
            "This measures agreement with analysts, not scam-detection recall.",
        )
        decision_rows = [
            {"analyst_decision": decision, "count": count}
            for decision, count in review_metrics["decisions"].items()
        ]
        if decision_rows:
            st.dataframe(decision_rows, use_container_width=True, hide_index=True)
        else:
            st.caption("No analyst decisions have been recorded yet.")
    except requests.RequestException:
        st.caption("Analyst-feedback metrics are temporarily unavailable.")

    _section_heading(
        "Safety and release quality",
        "Run these offline tests before a release. They are separate from live operating metrics and do not "
        "alter production counters.",
    )
    gate_rows = _labelled_rows(samples, "copilot_gate_failures_total")
    if gate_rows:
        st.dataframe(gate_rows, use_container_width=True, hide_index=True)
    else:
        st.success("No gate failures recorded in this API process.")
        with st.popover("ⓘ What does this mean?"):
            st.write(
                "No deterministic evidence, citation, confidence, prohibited-action or PII gate "
                "has failed since this local API was started. This counter resets on an API restart "
                "and is not a substitute for the offline evaluation suite."
            )
    if st.button(
        "Run offline evaluation suite",
        key="run_golden_evaluation",
        help=(
            "Runs four free, deterministic release suites: workflow, RAG retrieval, analyst "
            "conversation, and negative/safety cases. It does not use Nebius or alter live metrics."
        ),
    ):
        golden_response = requests.get(
            f"{API_URL}/evals/golden", headers=_api_headers(), timeout=20
        )
        rag_response = requests.get(f"{API_URL}/evals/rag", headers=_api_headers(), timeout=20)
        conversation_response = requests.get(
            f"{API_URL}/evals/conversation", headers=_api_headers(), timeout=20
        )
        safety_response = requests.get(
            f"{API_URL}/evals/safety", headers=_api_headers(), timeout=20
        )
        if all(
            response.ok
            for response in (golden_response, rag_response, conversation_response, safety_response)
        ):
            st.session_state["golden_report"] = golden_response.json()
            st.session_state["rag_report"] = rag_response.json()
            st.session_state["conversation_report"] = conversation_response.json()
            st.session_state["safety_report"] = safety_response.json()
        else:
            failed_response = next(
                response
                for response in (
                    golden_response,
                    rag_response,
                    conversation_response,
                    safety_response,
                )
                if not response.ok
            )
            st.error(failed_response.text)
    report = st.session_state.get("golden_report")
    if report:
        _metric_help(
            st,
            "Golden evaluation pass rate",
            f"{report['pass_rate']:.0%}",
            "Percentage of the 20 pre-labelled end-to-end cases that met the expected route, "
            "recommendation, evidence, citations and gates. This is the primary offline release check.",
        )
        st.caption(
            "Evidence coverage: "
            f"{report['summary']['required_evidence_coverage']:.0%} · "
            "Citation coverage: "
            f"{report['summary']['required_citation_coverage']:.0%} · "
            f"Gates: {report['summary']['gate_pass_rate']:.0%} · "
            f"Policy P@4: {report['summary']['policy_precision_at_4_lower_bound']:.0%} · "
            f"Policy R@4: {report['summary']['policy_recall_at_4']:.0%}"
        )
        st.dataframe(report["cases"], use_container_width=True, hide_index=True)
    rag_report = st.session_state.get("rag_report")
    if rag_report:
        _metric_help(
            st,
            "RAG retrieval release pass rate",
            f"{rag_report['pass_rate']:.0%}",
            "Percentage of the four curated retrieval queries that returned the expected approved "
            "policy with the required confidence. It catches retrieval regressions before release.",
        )
        st.dataframe(rag_report["cases"], use_container_width=True, hide_index=True)
    conversation_report = st.session_state.get("conversation_report")
    if conversation_report:
        _metric_help(
            st,
            "Conversation evaluation pass rate",
            f"{conversation_report['pass_rate']:.0%}",
            "Percentage of six behavioural test cases where Meridian correctly answered, clarified, "
            "refused a prohibited action, or routed to insufficient evidence.",
        )
        st.dataframe(conversation_report["cases"], use_container_width=True, hide_index=True)
    safety_report = st.session_state.get("safety_report")
    if safety_report:
        safety_summary = safety_report["summary"]
        _metric_help(
            st,
            "Safety release pass rate",
            f"{safety_report['pass_rate']:.0%}",
            "Percentage of negative cases that correctly stopped, refused, or blocked unsafe output. "
            "It includes missing evidence, unavailable policy, prohibited actions and PII tests.",
        )
        st.caption(
            "Safe-failure block rate: "
            f"{safety_summary['safe_failure_block_rate']:.0%} · "
            "Harmful-output block rate: "
            f"{safety_summary['harmful_output_block_rate']:.0%} · "
            "Harmful candidate share: "
            f"{safety_summary['harmful_output_rate']:.0%}"
        )
        st.dataframe(safety_report["cases"], use_container_width=True, hide_index=True)
    _section_heading(
        "Evaluation experiments",
        "Save an approved deterministic baseline after a release check. Later runs compare the same "
        "categories and flag any metric that falls; only deliberately approved trade-offs should regress.",
    )
    baseline_name = st.text_input(
        "Baseline name",
        value="release-candidate-v1",
        help="Use a short lowercase label, for example release-candidate-v1 or reranker-tuning-a.",
    )
    experiment_columns = st.columns(2)
    if experiment_columns[0].button(
        "Compare with saved baselines",
        help="Runs the deterministic local release suites and compares category-level metrics to each saved baseline.",
    ):
        response = requests.get(f"{API_URL}/evals/experiments", headers=_api_headers(), timeout=45)
        if response.ok:
            st.session_state["evaluation_experiments"] = response.json()
        else:
            st.error(response.text)
    if experiment_columns[1].button(
        "Save current baseline",
        help="Stores the current deterministic offline metrics under this label. It stores only aggregate metrics, not prompts or case content.",
    ):
        response = requests.post(
            f"{API_URL}/evals/experiments/baselines/{baseline_name}",
            headers=_api_headers(),
            timeout=45,
        )
        if response.ok:
            st.session_state["evaluation_experiments"] = response.json()
            st.success(f"Saved baseline: {response.json()['baseline']['name']}")
        else:
            st.error(response.text)
    experiment_report = st.session_state.get("evaluation_experiments")
    if experiment_report:
        comparisons = experiment_report.get("comparisons", [])
        if comparisons:
            for comparison in comparisons:
                status = (
                    "⚠️ Regression detected" if comparison["has_regression"] else "✅ No regression"
                )
                st.markdown(f"**{comparison['name']} — {status}**")
                st.dataframe(comparison["metrics"], use_container_width=True, hide_index=True)
        else:
            st.caption(
                "No saved baseline yet. Run the offline suite, then save the current metrics."
            )
    judge_case = st.selectbox(
        "Generation judge case",
        [f"CASE-AU-{index:03d}" for index in range(1, 21)],
        help=(
            "Choose one synthetic case to assess its generated narrative. This does not make a "
            "payment decision or update the live workflow metrics."
        ),
    )
    if st.button(
        "Run LLM quality judge",
        key="run_generation_judge",
        help=(
            "Makes one Nebius evaluation call. A separate model scores groundedness, clarity and safe "
            "actionability. Treat it as an additional signal, not a safety gate."
        ),
    ):
        response = requests.post(
            f"{API_URL}/evals/generation-judge/{judge_case}",
            headers=_api_headers(),
            timeout=45,
        )
        if response.ok:
            st.session_state["generation_judge"] = response.json()
        else:
            st.error(response.text)
    judge_result = st.session_state.get("generation_judge")
    if judge_result:
        judge_columns = st.columns(3)
        _metric_help(
            judge_columns[0],
            "LLM judged groundedness",
            f"{judge_result['score']:.0%}",
            "A separate LLM's assessment of whether the narrative is supported by available evidence. "
            "It is an additional signal, not a safety gate or final decision.",
        )
        _metric_help(
            judge_columns[1],
            "LLM judged clarity",
            f"{judge_result['clarity_score']:.0%}",
            "Whether the draft is concise and understandable for an analyst. This is a quality signal, "
            "not a claim of factual correctness.",
        )
        _metric_help(
            judge_columns[2],
            "LLM judged actionability",
            f"{judge_result['actionability_score']:.0%}",
            "Whether the draft identifies a safe, human-owned next step. It must never reward direct "
            "account or payment actions.",
        )
        st.caption(judge_result["rationale"])
    st.caption("The LLM quality judge consumes one Nebius evaluation call.")
    st.caption(
        "Updates automatically every 10 seconds. Offline evaluation runs do not affect "
        "live metrics."
    )


st.set_page_config(
    page_title="Meridian — Payment Scam Review Copilot", page_icon="◇", layout="wide"
)
st.markdown(
    """
    <style>
    html, body, .stApp, [data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"] {
        font-family: 'Source Sans Pro', sans-serif;
    }
    .stApp { background: #f7f9fc; color: #102a43; }
    h1, h2, h3 { color: #102a43; }
    .section-heading { color: #102a43; margin: 1.2rem 0 0.6rem; }
    mark { background: #fde68a; color: #713f12; border-radius: 3px; padding: 0.05rem 0.2rem; }
    .source-match { display: inline; background: #ede9fe; border-left: 3px solid #7c3aed;
        border-radius: 3px; padding: 0.2rem 0.3rem; line-height: 1.8; }
    .metric-card { min-height: 116px; background: #ffffff; border: 1px solid #d9e2ec;
        border-radius: 10px; padding: 0.8rem 1rem; box-sizing: border-box; }
    .metric-card strong { display: block; color: #2d3748; font-size: 2.4rem; line-height: 1.2;
        font-weight: 500; margin-top: 0.35rem; }
    .metric-label { color: #2d3748; font-weight: 600; }
    button[data-baseweb="tab"] { font-weight: 650; border-radius: 9px 9px 0 0; }
    button[data-baseweb="tab"]:first-child { color: #0f766e; background: #e6fffb; }
    button[data-baseweb="tab"]:nth-child(2) { color: #5b3b93; background: #f4efff; }
    .workflow-panel { background: #ffffff; border-left: 4px solid #0f766e; border-radius: 8px; padding: 0.75rem 1rem; margin: 0.5rem 0 1rem; }
    .decision-panel { background: #fff7ed; border-left: 4px solid #ea580c; border-radius: 8px; padding: 0.75rem 1rem; margin: 0.5rem 0 0.75rem; }
    .optional-panel { background: #eff6ff; border-left: 4px solid #2563eb; border-radius: 8px; padding: 0.75rem 1rem; margin: 0.75rem 0; }
    .status-card { min-height: 120px; border-radius: 10px; padding: 0.8rem; border: 1px solid #d9e2ec; background: #ffffff; }
    .status-card strong { display: block; font-size: 1.5rem; margin: 0.25rem 0; }
    .status-card small { color: #52606d; }
    .status-card.good { border-left: 5px solid #16a34a; }
    .status-card.watch { border-left: 5px solid #d97706; background: #fffbeb; }
    .status-card.bad { border-left: 5px solid #dc2626; background: #fef2f2; }
    .status-card.neutral { border-left: 5px solid #64748b; }
    .inline-tooltip { position: relative; display: inline-flex; align-items: center; justify-content: center;
        width: 1.05rem; height: 1.05rem; border: 1px solid #94a3b8; border-radius: 50%; color: #475569;
        font-size: 0.72rem; font-weight: 700; cursor: help; vertical-align: middle; }
    .tooltip-content { visibility: hidden; opacity: 0; position: absolute; z-index: 1000; top: 1.45rem;
        left: -0.5rem; width: 260px; padding: 0.65rem 0.75rem; background: #102a43; color: #ffffff;
        border-radius: 8px; box-shadow: 0 8px 22px rgba(15, 23, 42, 0.24); font-size: 0.78rem;
        font-weight: 400; line-height: 1.35; transition: opacity 0.12s ease; }
    .inline-tooltip:hover .tooltip-content, .inline-tooltip:focus .tooltip-content {
        visibility: visible; opacity: 1; }
    .stButton > button, .stFormSubmitButton > button {
        background: #0f766e;
        color: #ffffff;
        border: 0;
        border-radius: 8px;
    }
    .stButton > button:hover, .stFormSubmitButton > button:hover {
        background: #115e59;
        color: #ffffff;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.title("Meridian — Payment Scam Review Copilot")
st.caption(
    "Meridian helps financial-crime analysts assemble evidence-backed, policy-cited review briefs "
    "for unusual customer-authorised payments, while keeping every decision and action with a "
    "human."
)

try:
    cases = requests.get(f"{API_URL}/cases", headers=_api_headers(), timeout=3).json()
except requests.RequestException:
    st.error(
        "The FastAPI backend is unavailable. Start it with "
        "`uv run uvicorn copilot.api:app --reload`."
    )
    st.stop()

analyst_tab, operations_tab = st.tabs(["Analyst workspace", "Operations"])

with analyst_tab:
    normal_cases = [case for case in cases if case["case_id"].startswith("CASE-AU-")]
    labels = {case["label"]: case["case_id"] for case in normal_cases}
    _section_heading(
        "1. Select an alert",
        "This is a synthetic queue for the demonstration. Selecting an alert does not make a decision or "
        "change customer data.",
    )
    selected_label = st.selectbox(
        "Alert queue",
        labels,
        key="selected_alert_label",
        on_change=_clear_selected_case_result,
        label_visibility="collapsed",
        help="Choose a synthetic alert to investigate. Selecting it only changes the demo workspace; it does not take action on a customer account.",
    )
    case_id = labels[selected_label]
    selected_case = next(case for case in normal_cases if case["case_id"] == case_id)
    st.markdown(
        f"<div class='workflow-panel'><strong>Why it entered the queue</strong><br>"
        f"{_highlight_keywords(selected_case.get('reason', 'Synthetic alert selected for review.'))}</div>",
        unsafe_allow_html=True,
    )
    if st.button(
        "Prepare review brief",
        type="primary",
        help="Runs the evidence, policy retrieval, answerability, synthesis and safety workflow for this selected case.",
    ):
        streamed_result = _stream_investigation(case_id)
        if streamed_result is not None:
            st.session_state["result"] = streamed_result

    with st.expander("Control-test scenarios: demonstrate safe failure"):
        st.caption(
            "These synthetic scenarios are intentionally separate from the 20 normal analyst cases. "
            "They demonstrate that Meridian stops safely rather than inventing missing evidence."
        )
        control_options = {
            "Missing alerted-transaction evidence": ("CASE-CTRL-001", None),
            "Approved-policy source unavailable": ("CASE-CTRL-002", "policy_source_unavailable"),
        }
        selected_control = st.selectbox(
            "Safe-failure scenario",
            control_options,
            help="Choose a controlled failure mode for demonstration only. It does not modify the normal alert queue or policy corpus.",
        )
        control_case_id, control_mode = control_options[selected_control]
        if st.button(
            "Run control test",
            help="Runs the selected safe-failure path. The expected result is Insufficient Evidence, with synthesis skipped.",
        ):
            streamed_result = _stream_investigation(control_case_id, control_mode)
            if streamed_result is not None:
                st.session_state["result"] = streamed_result

    result = st.session_state.get("result")
    if result:
        result_case_id = result.get("case_id")
        if result_case_id != case_id:
            st.info(
                f"Showing the most recent control-test result for {result_case_id}. "
                f"Select or rerun {case_id} to display its review brief."
            )
        left, right = st.columns([2, 1])
        with left:
            _section_heading(
                "2. Meridian's review brief",
                "Generated from the selected case, approved policy and deterministic controls. It is a draft "
                "for review—not a decision and not an instruction to act.",
            )
            draft = result.get("draft")
            if draft:
                st.markdown("**Evidence-backed assessment**")
                st.markdown(f"- {_highlight_keywords(draft['summary'])}", unsafe_allow_html=True)
                st.markdown("**Key risk indicators**")
                for signal in draft["observed_signals"]:
                    st.markdown(f"- {_highlight_keywords(signal)}", unsafe_allow_html=True)
                st.markdown("**Recommended next step**")
                st.markdown(f"- {draft['recommendation'].replace('_', ' ').title()}")
                with st.expander("Evidence, policy and confidence rationale"):
                    st.caption(
                        f"Combined confidence: {draft['confidence']:.0%} "
                        f"({draft['confidence_band']})."
                    )
                    for rationale in draft["confidence_rationale"]:
                        st.markdown(f"- {rationale}")
                    st.markdown("**Policy citations**")
                    st.caption(
                        "Purple highlight marks the retrieved policy sentence most relevant to the "
                        "current case. The full passage is retained for verification."
                    )
                    for citation in draft["policy_citations"]:
                        st.caption(
                            f"{citation['policy_id']} v{citation['policy_version']} - "
                            f"{citation['section']}"
                        )
                        st.markdown(
                            _highlight_retrieved_passage(
                                citation["excerpt"], draft["observed_signals"]
                            ),
                            unsafe_allow_html=True,
                        )
            else:
                st.warning("No brief was produced. The workflow safely lacks sufficient evidence.")
        with right:
            _section_heading(
                "Controls applied",
                "These are automatic safety checks. They explain whether Meridian had enough grounded evidence "
                "to create a brief; they do not approve a payment action.",
            )
            _metric_help(
                st,
                "Route",
                result.get("route", "unknown").replace("_", " ").title(),
                "The safe workflow destination. Human Review means an analyst should decide; Insufficient Evidence means Meridian did not have enough grounded context to draft safely.",
            )
            assessment = result.get("retrieval_assessment")
            if assessment:
                _metric_help(
                    st,
                    "Policy confidence",
                    f"{assessment['confidence']:.0%}",
                    "Confidence in the approved-policy retrieval, not the probability of a scam. It reflects the retrieval evidence available for this brief.",
                )
                st.caption(
                    f"{assessment['search_mode'].title()} · {assessment['confidence_band'].title()}"
                )
            answerability_gate = result.get("answerability_gate")
            if answerability_gate and not answerability_gate["passed"]:
                st.warning("Policy answerability gate: insufficient evidence for drafting.")
                st.caption("; ".join(answerability_gate["reasons"]))
            passed = sum(gate["passed"] for gate in result.get("gates", []))
            _metric_help(
                st,
                "Brief safety checks",
                f"{passed}/{len(result.get('gates', []))}",
                "Checks that the draft has sufficient evidence and citations, meets the confidence floor, does not propose prohibited actions, and minimises PII. It does not determine whether a payment is legitimate.",
            )
            with st.expander("Control details"):
                generation_gate = result.get("generation_gate")
                if generation_gate:
                    icon = "✅" if generation_gate["passed"] else "⚠️"
                    st.write(
                        f"{icon} Generation grounding gate "
                        f"({'passed' if generation_gate['passed'] else 'fallback used'})"
                    )
                    if generation_gate["reasons"]:
                        st.caption("; ".join(generation_gate["reasons"]))
                for gate in result.get("gates", []):
                    icon = "✅" if gate["passed"] else "⛔"
                    st.write(f"{icon} {gate['gate_name'].replace('_', ' ').title()}")
                    if gate["reasons"]:
                        st.caption("; ".join(gate["reasons"]))
            st.markdown(
                "<div class='decision-panel'><strong>3. Analyst action required</strong><br>"
                "Review the brief and controls, then record your own outcome. Only this section is for you to complete."
                "</div>",
                unsafe_allow_html=True,
            )
            with st.form("analyst_review"):
                decision = st.selectbox(
                    "Outcome",
                    ["approved", "edited", "more_evidence", "insufficient_evidence", "escalated"],
                    help="Your final analyst outcome. This is the only point where Meridian records a decision; choose the outcome that reflects your own review.",
                )
                rationale = st.text_area(
                    "Rationale",
                    placeholder="Required before recording the final outcome.",
                    help="Briefly explain your decision. This becomes the analyst outcome record and supports later online evaluation.",
                )
                submitted = st.form_submit_button("Record decision")
            if submitted and len(rationale.strip()) >= 3:
                review = {
                    "case_id": result["case_id"],
                    "decision": decision,
                    "rationale": rationale.strip(),
                    "decided_at": datetime.now().astimezone().isoformat(),
                }
                response = requests.post(
                    f"{API_URL}/cases/{result['case_id']}/review",
                    headers=_api_headers(),
                    json=review,
                    timeout=10,
                )
                if response.ok:
                    feedback_status = response.json().get("langsmith_feedback_published")
                    st.success(
                        "Decision recorded locally"
                        + (
                            " and attached to its LangSmith trace."
                            if feedback_status == "true"
                            else "."
                        )
                    )
                else:
                    st.error(response.text)
            elif submitted:
                st.warning("Provide a short rationale before recording a decision.")
            st.markdown(
                "<div class='optional-panel'><strong>Optional: ask Meridian about this case</strong><br>"
                "Use this to clarify evidence or policy. It cannot take action, and every answer remains grounded "
                "in the case and approved policy.</div>",
                unsafe_allow_html=True,
            )
            with st.form("case_conversation_form"):
                question = st.text_input(
                    "Follow-up question",
                    placeholder="Why was this payment escalated? What policy applies?",
                    help="Ask about current case evidence, policy citations, the recommendation or missing information. Meridian cannot execute actions or make the final decision.",
                )
                asked = st.form_submit_button("Ask Meridian")
            if asked and question.strip():
                chat_response: requests.Response | None = None
                try:
                    with st.spinner("Checking current case evidence and approved policy…"):
                        chat_response = requests.post(
                            f"{API_URL}/cases/{result['case_id']}/chat",
                            headers=_api_headers(),
                            json={"question": question.strip()},
                            timeout=45,
                        )
                except requests.RequestException as error:
                    st.error(
                        "Meridian could not complete the follow-up before the connection timed out. "
                        f"Please try again. Technical detail: {error}"
                    )
                    chat_response = None
                if chat_response is not None and chat_response.ok:
                    st.session_state["case_conversation_result"] = chat_response.json()
                elif chat_response is not None:
                    try:
                        detail = chat_response.json().get("detail", chat_response.text)
                    except ValueError:
                        detail = chat_response.text
                    st.error(f"Meridian could not answer this follow-up: {detail}")
            conversation = st.session_state.get("case_conversation_result")
            if conversation and conversation["case_id"] == result["case_id"]:
                st.caption(f"Route: {conversation['route'].replace('_', ' ')}")
                st.write(conversation["reply"])
                if conversation["citations"]:
                    st.caption("Policy citations: " + ", ".join(conversation["citations"]))
                with st.expander("Conversation history"):
                    for turn in conversation["history"]:
                        st.markdown(f"**Analyst:** {turn['question']}")
                        st.markdown(f"**Meridian:** {turn['reply']}")

with operations_tab:
    st.header("Operations dashboard")
    st.caption(
        "Aggregate health view. Use LangSmith for the complete trace tree of one investigation."
    )
    _operations_dashboard()
