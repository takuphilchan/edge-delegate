"""Record supplied human decisions or export a new reviewed pilot; no automatic acceptance."""

import argparse
import json
from pathlib import Path

from edge_delegate.data.fingerprint import dataset_fingerprint
from edge_delegate.data.review import SPLITS, validate_review_dataset
from edge_delegate.data.review_ledger import ReviewLedger

from .cli import _load_json_object
from .jsonio import load_jsonl
from .review_workspace import verify_policy_document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    append = commands.add_parser("append")
    append.add_argument("--record-id", required=True)
    append.add_argument("--submission", type=Path, required=True)
    export = commands.add_parser("export")
    export.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = _load_json_object(args.directory / "manifest.json")
        verify_policy_document(args.directory, manifest)
        splits = {split: load_jsonl(args.directory / f"{split}.jsonl") for split in SPLITS}
        validate_review_dataset(splits, manifest, require_review=False)
        ledger = ReviewLedger(args.ledger)
        if args.command == "append":
            record = next(
                (r for rows in splits.values() for r in rows if r["record_id"] == args.record_id),
                None,
            )
            if record is None:
                raise ValueError("record not found in verified workspace")
            result = ledger.append(record, _load_json_object(args.submission))
            print(json.dumps({"appended_sha256": result["sha256"], "stage": result["stage"]}))
        else:
            # Require complete real review before publishing a new pilot snapshot.
            reviewed = {
                split: [ledger.reviewed_record(row) for row in rows]
                for split, rows in splits.items()
            }
            manifest["split_sha256"] = {
                split: dataset_fingerprint(rows) for split, rows in reviewed.items()
            }
            report = validate_review_dataset(reviewed, manifest, require_review=False)
            args.output.mkdir(parents=True, exist_ok=False)
            for split, rows in reviewed.items():
                (args.output / f"{split}.jsonl").write_text(
                    "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8"
                )
            for name, value in (
                ("manifest.json", manifest),
                ("review-history.json", ledger.events()),
                ("review-check.json", report),
            ):
                (args.output / name).write_text(
                    json.dumps(value, indent=2) + "\n", encoding="utf-8"
                )
            (args.output / "POLICY.md").write_text(
                (args.directory / "POLICY.md").read_text(encoding="utf-8"),
                encoding="utf-8",
                newline="\n",
            )
            print(
                json.dumps(
                    {
                        "output": str(args.output),
                        "accepted_count": report["accepted_count"],
                        "training_eligible": False,
                    }
                )
            )
        return 0
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
