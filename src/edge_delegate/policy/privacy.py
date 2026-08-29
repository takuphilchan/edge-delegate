"""Deterministic external-data privacy checks."""

from edge_delegate.contracts import ExternalHandoff, Policy, PrivacyClass


def disallowed_handoff_classes(
    handoff: ExternalHandoff, policy: Policy
) -> frozenset[PrivacyClass]:
    if not policy.external_allowed:
        return handoff.included_privacy_classes
    return handoff.included_privacy_classes - policy.external_privacy_classes

