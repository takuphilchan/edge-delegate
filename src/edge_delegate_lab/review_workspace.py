"""Read-only policy integrity and readable review status; never grant approvals."""

import re
from hashlib import sha256
from pathlib import Path

from .jsonio import MAX_RECORD_BYTES


def verify_policy_document(directory: Path, manifest):
    """Match the pilot writer's UTF-8, newline-normalized policy fingerprint.

    Older review workspaces may have neither a policy file nor a document hash.
    Their version-only policy reference is reported as unverified, never as a match.
    A present document requires a binding; a claimed binding requires its document.
    """
    path = directory / "POLICY.md"
    if "policy_document_sha256" not in manifest:
        if path.exists():
            raise ValueError("POLICY.md exists but manifest has no policy document fingerprint")
        return {"status": "not_provided", "sha256": None}
    expected = manifest["policy_document_sha256"]
    if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise ValueError("invalid policy document fingerprint")
    with path.open("rb") as handle:
        payload = handle.read(MAX_RECORD_BYTES + 1)
    if len(payload) > MAX_RECORD_BYTES:
        raise ValueError("policy document exceeds the size limit")
    policy = payload.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    actual = sha256(policy.encode("utf-8")).hexdigest()
    if actual != expected:
        raise ValueError(
            "policy document fingerprint mismatch; preserve the old review and version the change"
        )
    return {"status": "verified", "sha256": actual}


def render_review_status(report):
    lines = [
        "Review workspace: structural checks passed (not semantic approval)",
        f"Mode: {report['review_mode']}",
        f"Policy document: {report['policy_document']['status']} (integrity only)",
        f"Accepted label reviews: {report['accepted_count']}/{report['record_count']}",
        "Training eligible: no. Release qualified: no.",
        "",
    ]
    for split, coverage in report["coverage"].items():
        lines.append(
            f"{split}: {coverage['cases']} cases, {coverage['families']} declared families"
        )
        if coverage["categories"]:
            lines.append(
                "  "
                + ", ".join(
                    f"{name}: {count}" for name, count in sorted(coverage["categories"].items())
                )
            )
        if coverage["missing_tasks"]:
            lines.append("  Missing tasks: " + ", ".join(coverage["missing_tasks"]))
        if coverage["missing_categories"]:
            lines.append("  Missing categories: " + ", ".join(coverage["missing_categories"]))
    lines.extend(
        [
            "",
            "Next: complete independent label review and resolve disagreements; do not auto-accept rows.",
        ]
    )
    return "\n".join(lines)
