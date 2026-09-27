from edge_delegate.evaluation.qualification import proportion, qualify


def test_qualification_rejects_missing_review_quality_and_timing_evidence():
    report = qualify({"cases": []}, {"cases": []}, {"runs": []}, {})
    assert not report["qualified"]
    assert not report["checks"]["matching_model_evidence"]
    assert not report["checks"]["independent_review"]
    assert not report["checks"]["warm_p95"]


def test_uncertainty_is_reported_without_calling_zero_failures_a_guarantee():
    score = proportion(200, 200)
    assert score["rate"] == 1
    assert score["wilson_95"][0] < 1
    assert proportion(0, 0)["rate"] is None


def test_interrupted_benchmark_is_not_complete_evidence():
    report = qualify({"cases": []}, {"cases": []}, {"runs": [], "complete": False}, {})
    assert not report["checks"]["benchmark_complete"]
