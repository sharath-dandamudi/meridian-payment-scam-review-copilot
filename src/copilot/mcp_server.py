"""Local MCP server exposing governed tools, policy resources and prompt templates."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from copilot.mcp_gateway import FraudDataGateway

ROOT_DIR = Path(__file__).resolve().parents[2]
gateway = FraudDataGateway(ROOT_DIR / "data" / "fixtures")
POLICY_DIR = ROOT_DIR / "knowledge_base" / "policy"
mcp = FastMCP("meridian-governed-review-mcp")


def _approved_policy_documents() -> dict[str, tuple[str, str, str]]:
    """Load the local policy corpus as immutable MCP resources for this demo."""
    documents: dict[str, tuple[str, str, str]] = {}
    for path in sorted(POLICY_DIR.glob("PAY-SCAM-*.md")):
        content = path.read_text(encoding="utf-8")
        _, frontmatter, body = content.split("---", maxsplit=2)
        metadata = {
            key.strip(): value.strip()
            for line in frontmatter.strip().splitlines()
            if ":" in line
            for key, value in [line.split(":", maxsplit=1)]
        }
        documents[metadata["policy_id"]] = (
            metadata["version"],
            metadata["title"],
            body.strip(),
        )
    return documents


APPROVED_POLICIES = _approved_policy_documents()


@mcp.tool()
def get_alert(case_id: str) -> dict[str, object]:
    """Read a synthetic alert by case identifier."""
    return gateway.get_alert(case_id).model_dump(mode="json")


@mcp.tool()
def get_account_profile(account_id: str) -> dict[str, object]:
    """Read minimum-necessary synthetic account context."""
    return gateway.get_account_profile(account_id).model_dump(mode="json")


@mcp.tool()
def get_transaction(transaction_id: str) -> dict[str, object]:
    """Read one synthetic transaction by identifier."""
    return gateway.get_transaction(transaction_id).model_dump(mode="json")


@mcp.tool()
def get_recent_transactions(account_id: str, limit: int = 20) -> list[dict[str, object]]:
    """Read recent synthetic transactions for an account; capped at 20 records."""
    bounded_limit = min(max(limit, 1), 20)
    return [
        transaction.model_dump(mode="json")
        for transaction in gateway.get_recent_transactions(account_id, bounded_limit)
    ]


@mcp.resource(
    "policy://approved/catalog",
    name="approved-policy-catalog",
    title="Approved policy catalogue",
    description=(
        "Versioned, fictional payment-scam policy resources approved for the Meridian demo."
    ),
    mime_type="text/markdown",
)
def approved_policy_catalog() -> str:
    """List the versioned policy resources available to an MCP client."""
    rows = ["# Meridian approved policy catalogue", ""]
    for policy_id, (version, title, _) in APPROVED_POLICIES.items():
        rows.append(f"- `{policy_id}` v{version} — {title}")
    return "\n".join(rows)


def _register_policy_resources() -> None:
    """Register an immutable MCP Resource URI for each approved policy version."""
    for policy_id, (version, title, body) in APPROVED_POLICIES.items():
        uri = f"policy://approved/{policy_id}/v{version}"

        def make_policy_resource(policy_body: str) -> Callable[[], str]:
            def policy_resource() -> str:
                """Return a complete locally versioned approved-policy document."""
                return policy_body

            return policy_resource

        mcp.resource(
            uri,
            name=f"{policy_id.lower()}-v{version}",
            title=f"{policy_id} v{version}: {title}",
            description="Read-only fictional approved policy for the Meridian demo.",
            mime_type="text/markdown",
        )(make_policy_resource(body))


_register_policy_resources()


@mcp.prompt(
    name="investigate-payment-alert",
    title="Investigate a payment alert",
    description=(
        "Reusable analyst prompt that scopes a governed, read-only payment-alert investigation."
    ),
)
def investigate_payment_alert(case_id: str) -> str:
    """Return a reusable MCP prompt; it cannot authorise a consequential action."""
    return f"""Investigate synthetic case `{case_id}` for an authorised financial-crime analyst.

Use only read-only evidence tools and approved policy resources. Gather factual evidence, cite
applicable policy, state material gaps, and prepare a neutral review brief. Do not assert fraud,
freeze or restrict an account, contact a customer, submit a report, or make the final outcome.
Route any consequential decision to a human analyst."""


@mcp.prompt(
    name="explain-policy-citation",
    title="Explain a policy citation",
    description=(
        "Reusable analyst prompt for explaining a policy passage without inventing case facts."
    ),
)
def explain_policy_citation(policy_id: str) -> str:
    """Return a reusable MCP prompt for a policy-citation explanation."""
    return f"""Explain the approved policy citation `{policy_id}` to a financial-crime analyst.

Use only the matching versioned policy resource. Distinguish the policy requirement from case
facts, state when the policy does not establish a conclusion, and do not recommend or execute a
consequential customer or account action."""


if __name__ == "__main__":
    mcp.run()
