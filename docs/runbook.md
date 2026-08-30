# Meridian operational runbook

## Pre-demo check

1. Confirm `GET /health` returns `ok` and `GET /ready` returns `ready`.
2. Run `GET /evals/golden` and `GET /evals/rag`; both must return a 100% pass rate.
3. Run `CASE-AU-001` once and confirm a LangSmith trace, high-confidence policy retrieval,
   passing gates, and `human_review` routing.

## Incident triage

| Symptom | First check | Safe response |
|---|---|---|
| Draft is missing | LangSmith trace and `errors` in the API response | Route to insufficient evidence; do not retry an action. |
| Nebius failure | `model_fallback` metric and `synthesise_case` span | Retain deterministic draft and human review; investigate provider status. |
| Hosted RAG failure | RAG fallback counter, trace, and retrieval rationale | Confirm the local versioned-policy fallback was used; investigate Pinecone/Nebius separately. |
| Low RAG confidence | RAG span, policy citations, and retrieval score | Request more evidence; do not increase confidence manually. |
| MCP tool error | MCP dashboard rows and corresponding tool span | Treat data as unavailable and route safely; never fabricate evidence. |
| Gate failure | `gate_results` and gate-failure metric | Do not expose the draft as actionable; correct source/prompt logic and rerun golden evals. |
| Trace upload failure | API logs and LangSmith endpoint/key configuration | Preserve local logs and audit data; resolve tracing separately from case handling. |

## Evaluation interpretation

- The workflow golden evaluation is an offline release gate: it checks expected route,
  recommendation, evidence, citations, and gates before changes are demonstrated or deployed.
- The RAG retrieval evaluation is a separate release gate. It tests expected approved-policy
  retrieval and confidence floors before generation is involved, separating retrieval defects
  from drafting defects.
- Both suites use the deterministic local baseline, so they are reproducible and do not spend
  Nebius credits. Use LangSmith experiments to compare the local and Pinecone paths.
- Policy Precision@4 is labelled-policy precision and should be interpreted as a lower bound until
  every useful policy for each case is exhaustively labelled. Recall@4 measures recovery of the
  required policy labels.
- Escalation precision/recall compare the draft recommendation to an analyst's final escalation
  disposition; they are not fraud-detection precision/recall.
- `POST /evals/generation-judge/{case_id}` is an explicit offline LLM-as-judge check for summary
  groundedness. It may use Nebius credits and informs evaluation only; deterministic runtime gates
  remain the production safety control.
- The dashboard's draft-usefulness rate is `approved + edited` divided by `approved + edited +
  more_evidence`. Escalated and insufficient-evidence cases remain separate because they describe
  case disposition or evidence availability, not analyst satisfaction.
- Add failed or surprising traces to the golden set only after an analyst documents the expected
  safe outcome.

## Recovery and data controls

- SQLite checkpoints recover in-progress local workflow state. A production deployment replaces
  this with Postgres and encrypted storage.
- Only synthetic fixture data and fictional policy documents may be sent to Nebius, Pinecone, or
  LangSmith in this project. Analyst-feedback comments are redacted for likely emails and long
  numeric identifiers before trace feedback is published.
- Rotation of a provider key requires updating the deployment secret and re-running the pre-demo
  check. Never place a secret in Git, screenshots, or documentation.

## Deployment controls

- `AUTH_ENABLED=true` requires an `X-API-Key`. Analyst keys may work cases; operations keys may
  access metrics and evaluations. Local demo mode is explicitly `AUTH_ENABLED=false`.
- Every response carries `X-Request-ID`; the same ID is attached to structured logs and LangSmith
  trace metadata for incident correlation.
- The in-memory rate limiter is suitable only for one local API process. Use a shared gateway or
  Redis-backed limiter when horizontally scaling.
- The supplied Prometheus rules flag a model/grounding fallback rate above 5% and low-confidence
  retrieval rate above 10%.
- SQLite remains the demo persistence layer. A genuine deployment must use managed, encrypted,
  backed-up Postgres and a secrets manager before storing any non-synthetic records.
