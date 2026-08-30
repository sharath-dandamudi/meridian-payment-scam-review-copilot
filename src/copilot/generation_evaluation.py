"""Optional LLM-as-judge evaluation for offline review of generated summaries."""

from __future__ import annotations

import json

from openai import OpenAI
from pydantic import BaseModel, Field

from copilot.drafting import NEBIUS_BASE_URL
from copilot.models import InvestigationDraft
from copilot.settings import Settings


class GenerationJudgeResult(BaseModel):
    grounded: bool
    score: float = Field(ge=0, le=1)
    clarity_score: float = Field(ge=0, le=1)
    actionability_score: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=500)


class NebiusGroundednessJudge:
    """Offline quality evaluator, never a runtime decision or safety control."""

    def __init__(self, settings: Settings) -> None:
        if settings.nebius_api_key is None:
            raise ValueError("Nebius key is required for LLM-as-judge evaluation.")
        self._client = OpenAI(
            base_url=NEBIUS_BASE_URL,
            api_key=settings.nebius_api_key.get_secret_value(),
            timeout=30,
        )
        self._model_name = settings.model_name

    def evaluate(self, draft: InvestigationDraft) -> GenerationJudgeResult:
        evidence = "\n".join(f"- {item}" for item in draft.observed_signals)
        policy = "\n".join(f"- {item.excerpt}" for item in draft.policy_citations)
        response = self._client.chat.completions.create(
            model=self._model_name,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an offline evaluation judge. Assess whether a summary is grounded "
                        "only in supplied evidence and policy. Do not make a fraud decision. "
                        "Score clarity (easy for an analyst to understand) and actionability. "
                        "Actionability means identifying an appropriate human next step without "
                        "directing a consequential action. Score each from 0 to 1. "
                        "Return only JSON "
                        "with grounded (boolean), score (groundedness 0 to 1), clarity_score "
                        "(0 to 1), actionability_score (0 to 1), and rationale."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "summary": draft.summary,
                            "evidence": evidence,
                            "policy_context": policy,
                        }
                    ),
                },
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Generation judge returned an empty response.")
        payload = json.loads(content)
        if isinstance(payload.get("rationale"), str):
            payload["rationale"] = payload["rationale"][:500]
        return GenerationJudgeResult.model_validate(payload)
