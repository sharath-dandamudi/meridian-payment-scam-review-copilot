"""Read-only application gateway mirroring the local MCP server capabilities."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import TypeVar

from langsmith import traceable

from copilot.cache import TTLCache
from copilot.metrics import CACHE_EVENTS, MCP_TOOL_CALLS, MCP_TOOL_DURATION, metrics_enabled
from copilot.models import AccountProfile, Alert, Transaction
from copilot.repositories import SyntheticFraudRepository

ToolResult = TypeVar("ToolResult")


class FraudDataGateway:
    """Controlled access layer used by the workflow and exposed through MCP.

    The gateway deliberately contains no write methods. This makes prohibited
    actions impossible at the interface level, rather than merely discouraged
    in a prompt.
    """

    def __init__(self, fixtures_dir: Path) -> None:
        self._repository = SyntheticFraudRepository(fixtures_dir)
        self._cache: TTLCache[object] = TTLCache(max_entries=128, ttl_seconds=30)

    @traceable(name="mcp.get_alert", run_type="tool")
    def get_alert(self, case_id: str) -> Alert:
        return self._cached_observe(
            "get_alert", f"alert:{case_id}", lambda: self._repository.get_alert(case_id)
        )

    @traceable(name="mcp.list_alerts", run_type="tool")
    def list_alerts(self) -> list[Alert]:
        return self._cached_observe("list_alerts", "alerts:all", self._repository.list_alerts)

    @traceable(name="mcp.get_account_profile", run_type="tool")
    def get_account_profile(self, account_id: str) -> AccountProfile:
        return self._cached_observe(
            "get_account_profile",
            f"account:{account_id}",
            lambda: self._repository.get_account_profile(account_id),
        )

    @traceable(name="mcp.get_transaction", run_type="tool")
    def get_transaction(self, transaction_id: str) -> Transaction:
        return self._cached_observe(
            "get_transaction",
            f"transaction:{transaction_id}",
            lambda: self._repository.get_transaction(transaction_id),
        )

    @traceable(name="mcp.get_recent_transactions", run_type="tool")
    def get_recent_transactions(self, account_id: str, limit: int = 20) -> list[Transaction]:
        return self._cached_observe(
            "get_recent_transactions",
            f"transactions:{account_id}:{limit}",
            lambda: self._repository.get_recent_transactions(account_id, limit),
        )

    def _cached_observe(
        self, tool_name: str, cache_key: str, operation: Callable[[], ToolResult]
    ) -> ToolResult:
        started_at = perf_counter()
        cached = self._cache.get(cache_key)
        if cached.hit:
            if metrics_enabled.get():
                CACHE_EVENTS.labels(cache_name="mcp_gateway", outcome="hit").inc()
                MCP_TOOL_CALLS.labels(tool_name=tool_name, outcome="cache_hit").inc()
                MCP_TOOL_DURATION.labels(tool_name=tool_name).observe(perf_counter() - started_at)
            return cached.value  # type: ignore[return-value]
        if metrics_enabled.get():
            CACHE_EVENTS.labels(cache_name="mcp_gateway", outcome="miss").inc()
        try:
            result = operation()
        except Exception:
            if metrics_enabled.get():
                MCP_TOOL_CALLS.labels(tool_name=tool_name, outcome="error").inc()
            raise
        else:
            self._cache.put(cache_key, result)
            if metrics_enabled.get():
                MCP_TOOL_CALLS.labels(tool_name=tool_name, outcome="success").inc()
            return result
        finally:
            if metrics_enabled.get():
                MCP_TOOL_DURATION.labels(tool_name=tool_name).observe(perf_counter() - started_at)
