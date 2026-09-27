from edge_delegate_lab.presentation import render_gateway


def report(status="executed", steps=()):
    return {
        "result": {"request_id": "request", "status": status, "execution": {"steps": steps}},
        "total_latency_ms": 23.5,
    }


def test_readable_replay_is_not_presented_as_a_new_action():
    rendered = render_gateway(
        report(steps=[{"capability_id": "sensor.read", "status": "replayed", "result": 24.5}])
    )
    assert "recorded results" in rendered
    assert "excludes model loading" in rendered
    assert "not evaluated" in rendered


def test_unknown_and_conflict_have_safe_next_actions():
    assert "do not blindly retry" in render_gateway(report("execution_unknown"))
    assert "original input" in render_gateway(report("request_conflict"))


def test_gateway_text_escapes_terminal_controls():
    value = report()
    value["result"]["message"] = "\x1b[2Jmalicious"
    assert "\x1b" not in render_gateway(value)
