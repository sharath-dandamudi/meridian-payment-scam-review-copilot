"""Defence-in-depth redaction for telemetry and external-observability payloads."""

from __future__ import annotations

import re

EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
LONG_NUMBER_PATTERN = re.compile(r"\b\d{6,}\b")


def redact_text(value: str) -> str:
    """Remove likely direct identifiers while preserving enough diagnostic context."""
    value = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", value)
    return LONG_NUMBER_PATTERN.sub("[REDACTED_NUMBER]", value)
