"""Bounded structured drafting with a deterministic safety fallback."""

from __future__ import annotations

import json
from typing import Protocol

from langsmith import get_current_run_tree, traceable
from openai import OpenAI
from pydantic import BaseModel, Field

from copilot.metrics import MODEL_ESTIMATED_COST_USD, MODEL_TOKENS, metrics_enabled
from copilot.models import InvestigationDraft
from copilot.settings import Settings

NEBIUS_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"


class DraftNarrative(BaseModel):
    """The only fields a model may contribute to a case draft."""

    summary: str = Field(min_length=20, max_length=750)


class DraftGenerator(Protocol):
    def generate(self, baseline: InvestigationDraft) -> InvestigationDraft: ...


class NebiusDraftGenerator:
    """Nebius adapter that validates JSON and cannot change evidence or disposition."""

    def __init__(
        self,
        api_key: str,
        model_name: str,
        input_cost_per_million_usd: float = 0.0,
        output_cost_per_million_usd: float = 0.0,
    ) -> None:
        self.client = OpenAI(base_url=NEBIUS_BASE_URL, api_key=api_key, timeout=30)
        self.model_name = model_name
        self.input_cost_per_million_usd = input_cost_per_million_usd
        self.output_cost_per_million_usd = output_cost_per_million_usd

    @traceable(name="nebius.structured_draft", run_type="llm")
    def generate(self, baseline: InvestigationDraft) -> InvestigationDraft:
        prompt = self._prompt(baseline)
        response = self.client.chat.completions.create(
            model=self.model_name,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You draft neutral financial-crime investigation narratives. "
                        "Return only valid JSON matching the requested fields. "
                        "Do not diagnose fraud, direct an operational action, or invent facts."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Nebius returned an empty structured response.")
        if response.usage is not None:
            input_tokens = response.usage.prompt_tokens or 0
            output_tokens = response.usage.completion_tokens or 0
            run_tree = get_current_run_tree()
            if run_tree is not None:
                metadata = run_tree.extra.setdefault("metadata", {})
                metadata["usage_metadata"] = {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": response.usage.total_tokens or 0,
                }
            if metrics_enabled.get():
                MODEL_TOKENS.labels(token_type="input").inc(input_tokens)
                MODEL_TOKENS.labels(token_type="output").inc(output_tokens)
                estimated_cost = (
                    input_tokens * self.input_cost_per_million_usd
                    + output_tokens * self.output_cost_per_million_usd
                ) / 1_000_000
                MODEL_ESTIMATED_COST_USD.inc(estimated_cost)
        narrative = DraftNarrative.model_validate(json.loads(content))
        return baseline.model_copy(
            update={"summary": narrative.summary}
        )

    @staticmethod
    def _prompt(baseline: InvestigationDraft) -> str:
        return json.dumps(
            {
                "task": "Create a concise, neutral analyst-facing narrative.",
                "return_exactly": {
                    "summary": "string",
                },
                "approved_evidence": baseline.observed_signals,
                "approved_limitations": baseline.limitations,
                "constraints": [
                    "Only restate the approved evidence and limitations.",
                    (
                        "Do not include names, account numbers, email addresses, "
                        "or payment instructions."
                    ),
                    (
                        "Do not say fraud is confirmed or advise freezing, restricting, "
                        "contacting, or reporting."
                    ),
                ],
            }
        )


def draft_generator_from_settings(settings: Settings) -> DraftGenerator | None:
    """Build the live adapter only when it is explicitly enabled and configured."""
    if not settings.live_model_enabled or settings.model_provider.lower() != "nebius":
        return None
    if settings.nebius_api_key is None:
        return None
    return NebiusDraftGenerator(
        settings.nebius_api_key.get_secret_value(),
        settings.model_name,
        settings.model_input_cost_per_million_usd,
        settings.model_output_cost_per_million_usd,
    )
