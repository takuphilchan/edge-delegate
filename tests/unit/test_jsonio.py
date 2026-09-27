import pytest

from edge_delegate_lab.jsonio import MAX_RECORD_BYTES, load_jsonl


@pytest.mark.parametrize("payload", ['{"x":1,"x":2}\n', '{"x":NaN}\n', "[]\n"])
def test_dataset_reader_rejects_ambiguous_or_non_object_json(tmp_path, payload):
    path = tmp_path / "data.jsonl"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError):
        load_jsonl(path)


def test_dataset_reader_bounds_each_line_before_decoding(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_bytes(b" " * (MAX_RECORD_BYTES + 1))
    with pytest.raises(ValueError, match="size limit"):
        load_jsonl(path)


def test_dataset_reader_preserves_unicode_and_skips_blank_lines(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_text('\n{"text":"25 °C"}\n', encoding="utf-8")
    assert load_jsonl(path) == [{"text": "25 °C"}]
