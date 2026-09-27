import pytest

from edge_delegate.data.split import split_records


def record(index, **metadata):
    return {
        "record_id": str(index),
        "metadata": {
            "template_id": str(index),
            "paraphrase_cluster": str(index),
            "device_family": "same",
            **metadata,
        },
    }


def test_splits_scale_with_group_count_and_join_shared_paraphrases():
    records = [record(index) for index in range(100)]
    records[1]["metadata"]["paraphrase_cluster"] = "0"
    splits = split_records(records)
    assert len(splits["test"]) >= 14
    assert len(splits["validation"]) >= 14
    assert any({"0", "1"} <= {r["record_id"] for r in members} for members in splits.values())


def test_safety_source_overlap_is_rejected():
    with pytest.raises(ValueError, match="overlap"):
        split_records([record(0), record(1, paraphrase_cluster="0", tags=["safety"])])
