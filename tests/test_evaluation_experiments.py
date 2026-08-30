from copilot.evaluation_experiments import EvaluationExperimentStore, EvaluationSnapshot


def test_experiment_store_flags_metric_regressions(tmp_path) -> None:
    store = EvaluationExperimentStore(tmp_path / "baselines.json")
    store.save_baseline(
        "baseline-v1",
        EvaluationSnapshot({"workflow.pass_rate": 1.0, "safety.pass_rate": 1.0}),
        {"workflow_version": "0.1.0"},
    )

    comparisons = store.compare(
        EvaluationSnapshot({"workflow.pass_rate": 0.9, "safety.pass_rate": 1.0})
    )

    assert len(comparisons) == 1
    assert comparisons[0]["has_regression"] is True
    assert comparisons[0]["metrics"][0]["status"] == "regression"
