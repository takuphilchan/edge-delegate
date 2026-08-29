"""Scoped approval checks for consequential capabilities."""

from datetime import UTC, datetime

from edge_delegate.contracts import CapabilityCard, Policy, SideEffect


def needs_approval(card: CapabilityCard, policy: Policy) -> bool:
    return card.approval_required or (
        policy.require_approval_for_physical and card.side_effect is SideEffect.PHYSICAL
    )


def has_approval(
    card: CapabilityCard,
    policy: Policy,
    request_id: str,
    plan_sha256: str,
    now: datetime | None = None,
) -> bool:
    if not needs_approval(card, policy):
        return True
    return (
        policy.approval_for(
            request_id,
            card.capability_id,
            plan_sha256,
            now or datetime.now(UTC),
        )
        is not None
    )
