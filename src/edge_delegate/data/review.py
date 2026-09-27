"""Fail-closed review-workspace checks. Draft v2 records are NOT training inputs.

Checks recorded evidence, not contributor identity, truth of provenance, or human
agreement with a request. No data generation, auto-label repair, or freeze occurs.
"""

from collections import Counter
from copy import deepcopy

from edge_delegate.evaluation.outcomes import _equal

from .fingerprint import content_fingerprint, dataset_fingerprint
from .reference_oracle import ORACLE_VERSION, TASKS, check_reference_plan, reference_effects
from .validate import validate_record

REVIEW_RECORD_VERSION = "edge-delegate-dataset.v2-draft"
SPLITS = ("train", "validation", "test", "safety")


def review_payload_fingerprint(record):
    """Bind the review to all example content except mutable review administration."""
    payload = {
        key: value for key, value in record.items() if key not in {"content_sha256", "metadata"}
    }
    payload["metadata"] = {
        key: value for key, value in record["metadata"].items() if key != "review"
    }
    return content_fingerprint(payload)


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"nonempty {name} is required")
    return value


def _strings(value, name, *, nonempty=False):
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f"{name} must be a list" + (" with entries" if nonempty else ""))
    for item in value:
        _text(item, name)
    if len(set(value)) != len(value):
        raise ValueError(f"duplicate {name}")
    return value


def validate_review_record(record, *, require_review=True):
    if not isinstance(record, dict) or record.get("schema_version") != REVIEW_RECORD_VERSION:
        raise ValueError("review requires explicitly versioned v2 draft records")
    unsigned = {key: value for key, value in record.items() if key != "content_sha256"}
    if record.get("content_sha256") != content_fingerprint(unsigned):
        raise ValueError("review record fingerprint mismatch")
    # Reuse existing wire/static checks on a private compatibility view. Never save
    # this view or teach the training loader to accept unapproved review records.
    legacy = deepcopy(record)
    legacy["schema_version"] = "edge-delegate-dataset.v1"
    legacy.pop("content_sha256")
    legacy["content_sha256"] = content_fingerprint(legacy)
    validate_record(legacy)
    metadata = record["metadata"]
    _text(metadata.get("scenario_group"), "scenario_group")
    if metadata.get("category") not in {
        "supported",
        "clarify",
        "deny",
        "restricted",
        "adversarial",
        "challenge",
    }:
        raise ValueError("unknown review category")
    if metadata["category"] == "supported" and record["expected_outcome"] != "executed":
        raise ValueError("supported category requires an executable outcome")
    if metadata["category"] == "restricted" and (
        record["expected_task"]["task"] in {"clarify", "deny"}
        or record["expected_outcome"] not in {"denied", "invalid_plan"}
    ):
        raise ValueError("restricted category requires a blocked intended action")
    for category in ("clarify", "deny"):
        if metadata["category"] == category and record["expected_task"]["task"] != category:
            raise ValueError("category does not match intended task")
    provenance = metadata.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("structured provenance required")
    _strings(provenance.get("source_ids"), "source_ids", nonempty=True)
    _strings(provenance.get("parent_ids"), "parent_ids")
    if provenance.get("method") not in {"human", "generated"}:
        raise ValueError("provenance method must be human or generated")
    if provenance["method"] == "generated":
        _text(provenance.get("generator"), "generator")
        if type(provenance.get("seed")) is not int:
            raise ValueError("generated provenance needs integer seed")
    review = metadata.get("review")
    if not isinstance(review, dict):
        raise ValueError("review ledger entry required")
    _text(review.get("author"), "author")
    _text(review.get("rationale"), "rationale")
    if review.get("status") not in {"pending", "accepted", "quarantined", "rejected"}:
        raise ValueError("unknown review status")
    if not _equal(review.get("author_decision"), record["expected_task"]):
        raise ValueError("author decision disagrees with expected task")
    if review["status"] == "accepted":
        if (
            _text(review.get("reviewer"), "reviewer").strip().casefold()
            == review["author"].strip().casefold()
        ):
            raise ValueError("reviewer must differ from author")
        if not _equal(review.get("reviewer_decision"), record["expected_task"]):
            raise ValueError(
                "unresolved reviewer decision; retain disagreements outside accepted set"
            )
        # Review covers both meaning and effects/context, not just a task label.
        if review.get("reviewed_payload_sha256") != review_payload_fingerprint(record):
            raise ValueError("review approval does not bind current context and expectations")
    elif require_review:
        raise ValueError("independent accepted review required")
    expected = reference_effects(
        record["expected_task"],
        record["state"]["values"],
        record["expected_outcome"],
        [card["capability_id"] for card in record["capabilities"]],
    )
    if not _equal(record["expected_effects"], expected):
        raise ValueError("expected effects disagree with independent fixture oracle")
    check_reference_plan(record)


def validate_review_dataset(splits, manifest, *, require_review=True):
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "edge-dataset-review.v1":
        raise ValueError("review manifest version is required")
    if manifest.get("catalog") != "local-display.v1" or manifest.get("oracle") != ORACLE_VERSION:
        raise ValueError("unsupported catalog/oracle version")
    _text(manifest.get("label_policy"), "label_policy version")
    if set(splits) != set(SPLITS) or any(not isinstance(rows, list) for rows in splits.values()):
        raise ValueError("review workspace requires train, validation, test, and safety lists")
    sources = manifest.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise ValueError("source registry required")
    for source_id, source in sources.items():
        _text(source_id, "source ID")
        if not isinstance(source, dict):
            raise ValueError("source entry must be an object")
        for field in ("family", "contributor", "rights"):
            _text(source.get(field), field)
        if source.get("exposure") not in {"fresh", "development"}:
            raise ValueError("source exposure must be recorded")
    owners, text_owners, records, record_splits = {}, {}, {}, {}
    coverage = {}
    accepted = 0
    for split in SPLITS:
        rows = splits[split]
        if manifest.get("split_sha256", {}).get(split) != dataset_fingerprint(rows):
            raise ValueError(f"{split} fingerprint mismatch")
        count = manifest.get("split_counts", {}).get(split)
        if type(count) is not int or count != len(rows):
            raise ValueError(f"{split} count mismatch")
        families = Counter()
        tasks, categories = Counter(), Counter()
        for record in rows:
            validate_review_record(record, require_review=require_review)
            identifier, metadata = record["record_id"], record["metadata"]
            if identifier in records:
                raise ValueError("duplicate record identifier across splits")
            records[identifier], record_splits[identifier] = record, split
            family = metadata["scenario_group"]
            for field in ("scenario_group", "template_id", "paraphrase_cluster"):
                if owners.setdefault((field, metadata[field]), split) != split:
                    raise ValueError("source family leakage across splits")
            for field, key in (
                ("catalog_version", "catalog"),
                ("label_policy", "label_policy"),
                ("oracle_version", "oracle"),
            ):
                if metadata.get(field) != manifest[key]:
                    raise ValueError(f"record {field} disagrees with manifest")
            for source_id in metadata["provenance"]["source_ids"]:
                source = sources.get(source_id)
                if source is None or source["family"] != family:
                    raise ValueError("unregistered or incompatible source family")
                if split in {"test", "safety"} and source["exposure"] != "fresh":
                    raise ValueError("development-exposed source in held-out split")
            bound_sources = {
                source_id: sources[source_id] for source_id in metadata["provenance"]["source_ids"]
            }
            if metadata.get("sources_sha256") != content_fingerprint(bound_sources):
                raise ValueError("source registry changed since record review")
            normalized = " ".join(record["request"]["text"].casefold().split())
            if text_owners.setdefault(normalized, split) != split:
                raise ValueError("duplicate request text across splits")
            families[family] += 1
            tasks[record["expected_task"]["task"]] += 1
            categories[metadata["category"]] += 1
            accepted += metadata["review"]["status"] == "accepted"
        coverage[split] = {
            "cases": len(rows),
            "families": len(families),
            "tasks": dict(tasks),
            "categories": dict(categories),
            "largest_family": max(families.values(), default=0),
            "missing_tasks": sorted(TASKS - tasks.keys()),
        }
        required_categories = (
            {"adversarial"} if split == "safety" else {"supported", "clarify", "deny", "restricted"}
        )
        coverage[split]["missing_categories"] = sorted(required_categories - categories.keys())
        if require_review and split != "safety" and TASKS - tasks.keys():
            raise ValueError(f"{split} lacks pilot task coverage")
        if require_review and required_categories - categories.keys():
            raise ValueError(f"{split} lacks pilot category coverage")
        if require_review and not rows:
            raise ValueError(f"{split} is empty")
    if not records:
        raise ValueError("empty review workspace")
    visited, visiting = set(), set()

    def visit(identifier):
        if identifier in visiting:
            raise ValueError("cyclic provenance")
        if identifier in visited:
            return
        visiting.add(identifier)
        record = records[identifier]
        provenance = record["metadata"]["provenance"]
        for parent_id in provenance["parent_ids"]:
            parent = records.get(parent_id)
            if parent is None:
                raise ValueError("unresolved parent record; register external roots as sources")
            if (
                record_splits[parent_id] != record_splits[identifier]
                or parent["metadata"]["scenario_group"] != record["metadata"]["scenario_group"]
                or not set(parent["metadata"]["provenance"]["source_ids"])
                <= set(provenance["source_ids"])
            ):
                raise ValueError("parent lineage crosses split/family or loses source ancestry")
            visit(parent_id)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in records:
        visit(identifier)
    return {
        "schema_version": "edge-dataset-review-report.v1",
        "valid": True,
        "review_mode": "accepted-pilot" if require_review else "draft",
        "record_count": len(records),
        "accepted_count": accepted,
        "coverage": coverage,
        "qualified": False,
        "training_eligible": False,
        "limitations": [
            "Checks declared review evidence, not reviewer identity or correctness of English labels.",
            "Exact normalized-text and declared-lineage checks are not near-duplicate review.",
            "Pilot coverage is not full dataset-v2 coverage or a frozen-test release gate.",
        ],
    }
