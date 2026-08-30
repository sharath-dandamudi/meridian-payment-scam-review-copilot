# Meridian — five-minute live demo guide

## Before recording

Start the API and Streamlit in separate terminals, open LangSmith on the Meridian project, and keep
the Operations tab ready in a second browser tab. Use only synthetic `CASE-AU-*` data.

## 0:00–0:30 — problem and boundary

State that Meridian supports, but never replaces, an Australian bank financial-crime analyst.
It handles synthetic unusual customer-authorised payment alerts and cannot freeze accounts,
contact customers, move money, or file a report.

## 0:30–1:45 — run an investigation

Select `CASE-AU-001` and prepare the draft. Point out the seven visible stages, evidence IDs,
approved-policy citations, high retrieval confidence, the cautious recommendation, and the required
human review. Say explicitly that the upstream monitoring system created the alert; Meridian does
not claim to be a fraud-detection engine.

## 1:45–2:45 — explain the trace

Open the matching LangSmith trace. Show the LangGraph nodes, MCP tool spans, Pinecone retrieval,
Nebius drafting, latency, gates, and final `human_review` route.

## 2:45–3:45 — show controls and observability

Open the operations dashboard. Explain the RAG confidence distribution, MCP errors, model fallback
rate, gate failures, cache hits/misses, and analyst-feedback outcomes.

## 3:45–4:30 — show evaluation and recovery

Run the offline suite. Explain the four layers: 20 workflow golden cases, RAG retrieval cases,
conversation routing cases, and negative safety cases. Show the named `pre-release-v1` baseline and
explain that later metric drops are flagged as regressions. Mention SQLite checkpoints locally and
Postgres in deployment.

## 4:30–5:00 — close with trade-offs

Explain that the MVP chooses a small bounded workflow over a broad autonomous agent. Pinecone and
Nebius improve realistic integration coverage; deterministic gates, local fallback, and human
approval preserve safety and debugging clarity.
