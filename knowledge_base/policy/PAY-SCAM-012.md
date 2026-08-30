---
policy_id: PAY-SCAM-012
version: 1.0
title: Fictional copilot resilience and fallback procedure
status: approved-for-demo
---

# Service degradation

If a model, policy-retrieval service, or evidence source is unavailable, preserve the failure reason and use the approved local fallback where available.

# Safety boundary

Service recovery must never bypass evidence, citation, confidence, PII, prohibited-action, or human-review controls. An unavailable required source results in insufficient evidence.
