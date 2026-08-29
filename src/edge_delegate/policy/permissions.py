"""Deterministic capability allowlist and permission checks."""

from edge_delegate.contracts import CapabilityCard, Policy


def capability_allowed(card: CapabilityCard, policy: Policy) -> bool:
    if card.capability_id in policy.denied_capabilities:
        return False
    return policy.allowed_capabilities is None or card.capability_id in policy.allowed_capabilities


def missing_permissions(card: CapabilityCard, policy: Policy) -> frozenset[str]:
    return card.permissions - policy.granted_permissions

