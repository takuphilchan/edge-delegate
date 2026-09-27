import json
import runpy
from pathlib import Path

import pytest

from edge_delegate.data import dataset_fingerprint, generate_records


def test_comparison_uses_canonical_validation_identity_and_rejects_other_splits(tmp_path):
    read = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts" / "compare_inference.py")
    )["load_validation_records"]
    records = generate_records()[:2]
    (tmp_path / "manifest.json").write_text(
        json.dumps({"split_sha256": {"validation": dataset_fingerprint(records)}})
    )
    source = tmp_path / "validation.jsonl"
    # Byte-level hashes differ with ordering/whitespace; canonical content is unchanged.
    source.write_text("\n".join(json.dumps(record) for record in reversed(records)) + "\n")
    assert read(source) == list(reversed(records))
    source.write_text(json.dumps(records[0]) + "\n")
    with pytest.raises(ValueError, match="validation split"):
        read(source)
