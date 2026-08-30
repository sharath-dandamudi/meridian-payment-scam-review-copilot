# Meridian stakeholder discussion guide

## Why is this agentic rather than a chatbot?

Meridian uses a stateful LangGraph workflow to select bounded next steps, call read-only data and
policy-retrieval capabilities, assess evidence, apply gates, and route to human review. It is
agentic in orchestration, but deliberately not autonomous in consequential banking decisions.

## Why not let the model decide whether a payment is fraudulent?

The model does not have reliable ground truth, regulatory accountability, or authority to make
customer-impacting decisions. I constrain it to a neutral summary while deterministic code owns
evidence, citations, confidence, gates, and routing; a financial-crime analyst owns the outcome.

## How does RAG reduce hallucination here?

The workflow retrieves only versioned approved policy content and attaches citations to the draft.
The generation prompt is bounded to the collected evidence, while citation and confidence gates
block weak drafts. Pinecone adds semantic retrieval; the local versioned retriever is a fallback.

## How do you evaluate the solution?

Offline golden cases act as a release gate: expected route, recommendation, evidence IDs, policy
citations, and gates must match. Online, analyst decisions are attached to LangSmith traces and
reported separately as approval, edit, more-evidence, insufficient-evidence, and escalation trends.

## Why are gates different from evaluations?

Gates are real-time controls that block an unsafe or unsupported draft in a live investigation.
Evaluations assess whether the system behaves well across a dataset or trace sample. A system can
pass an evaluation overall while a particular live draft correctly fails a gate.

## How do confidence thresholds work?

Evidence confidence and policy-retrieval confidence are calculated separately; final confidence is
the weaker component. High confidence is at least 0.80, moderate is 0.60–0.79, and below 0.60
routes to insufficient evidence. Any failed gate overrides confidence, and no score enables action.

## How would you troubleshoot a poor draft?

Start with the LangSmith trace tree: identify whether evidence, retrieval, model drafting, or gates
caused the result. Then inspect dashboard trends for RAG confidence, tool errors, model fallbacks,
and latency. Convert the confirmed failure into a golden case before changing prompts or logic.

## What is the MCP design choice?

The MCP boundary exposes only read-only alert, account, and transaction operations. This is a
security control in the interface itself: there is no tool that can freeze an account, contact a
customer, move funds, or submit a regulatory report.

## Where does A2A fit?

The evidence, policy, and synthesis roles exchange typed `AgentPacket` contracts that are portable
to separate A2A services. The MVP keeps them in one process to make debugging and deployment
reliable; a distributed A2A deployment is justified only when independent scaling or ownership is
needed.

## Why cache data in a fraud workflow?

Only non-authoritative, read-only fixture and policy lookups are cached with short bounded TTLs.
Cache metrics show hits and misses. Authoritative case decisions, analyst outcomes, and policy
versions are never treated as cache truth.

## What would change for production?

Replace local SQLite checkpoints/audit storage with encrypted, access-controlled Postgres; use a
proper secrets manager, service identity, external Prometheus retention, authenticated API access,
and a governed real-data integration. The human approval boundary and observability controls remain.
