"""Small, explicit API hardening controls suitable for the local MVP."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from hmac import compare_digest
from time import monotonic
from typing import Literal

from fastapi import HTTPException, Request, status

from copilot.settings import Settings

Role = Literal["analyst", "operations"]


class InMemoryRateLimiter:
    """Per-client sliding-window limiter; replace with a shared store in production."""

    def __init__(self, limit_per_minute: int) -> None:
        self._limit = limit_per_minute
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, client_key: str) -> bool:
        now = monotonic()
        window = self._requests[client_key]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self._limit:
            return False
        window.append(now)
        return True


def require_role(settings: Settings, *allowed_roles: Role) -> Callable[[Request], Role]:
    """Return a FastAPI dependency that is bypassed only in explicit local-demo mode."""

    def dependency(request: Request) -> Role:
        if not settings.auth_enabled:
            return "operations"
        supplied = request.headers.get("X-API-Key", "")
        analyst = settings.analyst_api_key.get_secret_value() if settings.analyst_api_key else ""
        operations = (
            settings.operations_api_key.get_secret_value() if settings.operations_api_key else ""
        )
        role: Role | None = None
        if analyst and compare_digest(supplied, analyst):
            role = "analyst"
        elif operations and compare_digest(supplied, operations):
            role = "operations"
        if role is None or role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="A valid API key with the required role is required.",
            )
        return role

    return dependency
