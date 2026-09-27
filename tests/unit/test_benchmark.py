from edge_delegate_lab.benchmark import benchmark, outcome_diagnostics


class FakeSession:
    def handle(self, request):
        return {
            "total_latency_ms": 2.0,
            "result": {"status": "execution_failed"},
            "timing": {},
            "generation_resources": None,
        }


def test_benchmark_retains_errors_and_incomplete_checkpoints():
    partials = []
    report = benchmark(FakeSession(), count=50, runs=2, checkpoint=partials.append)
    assert report["complete"] is True
    assert all(partial["complete"] is False for partial in partials)
    assert len(report["runs"]) == 2
    assert all(run["status_counts"] == {"execution_failed": 50} for run in report["runs"])
    assert report["runs"][0]["latency_by_status"]["execution_failed"]["count"] == 50
    assert partials[0]["runs"][0]["request_count"] == 50


def test_benchmark_keeps_rejection_stage_without_exception_text():
    result = outcome_diagnostics(
        {
            "status": "invalid_plan",
            "message": "secret user payload",
            "validation": {"issues": [{"code": "stale_state", "message": "secret"}]},
        }
    )
    assert result["stage"] == "validation_or_routing"
    assert result["validation_codes"] == ["stale_state"]
    assert "secret" not in str(result)
    assert outcome_diagnostics({"status": "invalid_plan"})["stage"] == "planning"
