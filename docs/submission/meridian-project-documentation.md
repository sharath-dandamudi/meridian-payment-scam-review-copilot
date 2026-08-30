# Meridian — Payment Scam Review Copilot

## Project overview

Meridian is a governed payment-scam review copilot for financial-crime analysts. It turns a synthetic alert for an unusual customer-authorised outbound payment into an evidence-backed, policy-cited review brief. It never freezes accounts, contacts customers, moves money, files reports, or makes the final decision; a human analyst owns every consequential outcome.

**Success measure:** an analyst receives a usable brief in under 15 minutes, with a target usefulness rate of at least 90%.

## What I built

1. A LangGraph coordinator validates the alert and holds typed workflow state.
2. An Evidence Agent uses read-only MCP-style tools to retrieve the alert, account profile, alerted payment, and recent transactions.
3. A Policy Retrieval Agent performs hybrid search: Pinecone semantic candidates plus local lexical candidates, followed by a cross-encoder reranker.
4. An answerability gate requires evidence, at least two policy citations, and sufficient retrieval confidence before drafting is allowed.
5. A Synthesis Agent creates a structured, cited draft. Nebius may refine only the narrative; a deterministic draft remains the safe fallback.
6. Grounding, evidence, citation, confidence, prohibited-action, and PII gates route either to Human Review or Insufficient Evidence.

## Design rationale and trade-offs

The system uses three bounded specialist roles—evidence collection, policy retrieval, and synthesis—coordinated by LangGraph. Pydantic packets provide typed A2A-style hand-offs, but the roles stay in one process for a debuggable MVP rather than becoming distributed agents.

The MCP design exposes only reads. The formal server demonstrates tools, immutable versioned policy resources, and constrained reusable prompts; the core workflow uses an equivalent in-process gateway to avoid needless network latency.

SQLite provides local LangGraph checkpoints and the audit store. Production would replace it with access-controlled Postgres, managed secrets, service identities, and governed bank-data interfaces.

## Data and tools

- 20 committed synthetic Australian-style payment-alert cases, account profiles, and transactions.
- 2 controlled failure cases: missing transaction evidence and unavailable policy source.
- 12 fictional, versioned payment-scam policy/SOP documents.
- Optional local preview support for public IBM AMLSim, labelled clearly as non-Australian synthetic simulation.
- Python, LangChain, LangGraph, Pydantic, Nebius Token Factory/Qwen, Pinecone, FastMCP, FastAPI, Streamlit, LangSmith, Prometheus-compatible metrics, and Pytest.

No real customer, account, transaction, or policy data is accepted by the demo.

## Evaluation, monitoring, and safety

- 20 golden workflow cases assert route, recommendation, evidence, citations, and gates.
- RAG cases assert expected policy and minimum retrieval confidence.
- Conversation cases assert answer, clarify, and refusal behaviour.
- Negative/safety cases assert safe failure for missing evidence, unavailable policy, prohibited account actions, harmful claims/actions, and PII leakage.
- The Operations dashboard shows workflow completion, MCP tool health, latency, fallback rate, RAG confidence, token/cost diagnostics, gate failures, and analyst outcome agreement.
- Named baselines support category-level regression comparison; LangSmith provides the full trace tree for one investigation.

## Representative coding prompts and iterations

1. “Build a smaller, production-minded LangGraph workflow for a payment-scam analyst copilot with checkpoints, explicit gates, fallbacks and human review.”
2. “Add hybrid policy retrieval using Pinecone semantic search, local lexical retrieval and a cross-encoder reranker; retain a local fallback.”
3. “Add an evidence gate after reranking so weak results route to insufficient evidence rather than drafting.”
4. “Use Pydantic structured outputs and prevent consequential tools or autonomous payment actions.”
5. “Add LangSmith traces, Prometheus metrics, offline golden evaluations, online analyst feedback, and a separate Operations dashboard.”
6. “Make the Streamlit analyst workflow easier to read: progress stages, evidence highlights, accessible metric explanations, and separate operational detail.”

Key iterations: hybrid retrieval with reranking; answerability before generation; separate analyst and operations surfaces; formal MCP resources/prompts; negative safety cases; and named evaluation baselines.

## Learnings

- Agentic value came from control flow, state, safety boundaries, and failure recovery—not a larger prompt.
- The answerability decision belongs after retrieval and before generation; fluent text cannot compensate for weak evidence.
- Observability needs two views: LangSmith for a trace and aggregate metrics for operational health.
- Reranking improves evidence selection but adds latency, so it should be measured against a stable baseline.
- Human feedback is the authoritative online signal; it measures agreement with analysts, not fraud-detection accuracy.

## Demo steps

1. Start FastAPI and Streamlit.
2. Select `CASE-AU-001` and prepare a review brief.
3. Show the matching LangSmith trace and Operations dashboard.
4. Run the offline suite, show the `pre-release-v1` baseline, then demonstrate one safe failure scenario.
