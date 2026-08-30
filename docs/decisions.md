# Decision log

| ID | Decision | Rationale | Status |
|---|---|---|---|
| ADR-001 | Start with one alert type and three specialist roles. | A small, fully observable workflow is more reliable and demonstrable than broad autonomous behaviour. | Accepted |
| ADR-002 | Use synthetic fixtures before downloading a public dataset. | Enables safe, deterministic tests and evaluation design before scale is introduced. | Accepted |
| ADR-003 | Use Streamlit with a separate FastAPI backend. | Fast demonstration surface without coupling UI and workflow logic. | Accepted |
| ADR-004 | Use read-only MCP tools. | Enforces the human-in-the-loop boundary for all consequential actions. | Accepted |
| ADR-005 | Use SQLite checkpoints for the local MVP, with Postgres as the deployment path. | Supports restart recovery and troubleshooting without introducing infrastructure the demo does not need. | Accepted |
| ADR-006 | Restrict Nebius to the narrative summary and retain deterministic controls. | Limits model variance to a non-consequential field and ensures provider failure has a safe fallback. | Accepted |
