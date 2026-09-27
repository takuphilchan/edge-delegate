from edge_delegate.evaluation.outcomes import check_effects


def test_numeric_equivalence_does_not_equate_booleans_with_numbers():
    expected = {"state": {"value": 12.0}, "invocations": []}
    assert check_effects(expected, state={"value": 12}, final_output=None, invocations=[])[0]
    expected["state"]["value"] = 1
    assert not check_effects(expected, state={"value": True}, final_output=None, invocations=[])[0]
