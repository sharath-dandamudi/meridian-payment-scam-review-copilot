import asyncio

from copilot.mcp_server import mcp


def test_mcp_server_exposes_versioned_policy_resources_and_prompt_templates() -> None:
    async def inspect_server() -> tuple[set[str], set[str], str, str]:
        resources = await mcp.list_resources()
        prompts = await mcp.list_prompts()
        policy = await mcp.read_resource("policy://approved/PAY-SCAM-003/v1.0")
        prompt = await mcp.get_prompt("investigate-payment-alert", {"case_id": "CASE-AU-001"})
        return (
            {str(resource.uri) for resource in resources},
            {item.name for item in prompts},
            policy[0].content,
            prompt.messages[0].content.text,
        )

    resources, prompts, policy_content, prompt_content = asyncio.run(inspect_server())

    assert "policy://approved/catalog" in resources
    assert "policy://approved/PAY-SCAM-003/v1.0" in resources
    assert {"investigate-payment-alert", "explain-policy-citation"} <= prompts
    assert "first-time-payee" in policy_content
    assert "CASE-AU-001" in prompt_content
