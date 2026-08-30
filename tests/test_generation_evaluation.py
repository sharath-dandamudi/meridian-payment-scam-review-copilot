from copilot.generation_evaluation import GenerationJudgeResult


def test_generation_judge_result_accepts_the_new_quality_scores() -> None:
    result = GenerationJudgeResult.model_validate(
        {
            "grounded": True,
            "score": 0.9,
            "clarity_score": 0.8,
            "actionability_score": 0.85,
            "rationale": "Grounded, clear and safely actionable.",
        }
    )

    assert result.clarity_score == 0.8
    assert result.actionability_score == 0.85
