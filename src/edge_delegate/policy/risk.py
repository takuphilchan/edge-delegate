"""Simple auditable risk classification independent of model confidence."""

from enum import IntEnum

from edge_delegate.contracts import CapabilityCard, PrivacyClass, SideEffect


class RiskLevel(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


def classify_capability(card: CapabilityCard) -> RiskLevel:
    if card.side_effect is SideEffect.PHYSICAL:
        return RiskLevel.CRITICAL
    if PrivacyClass.SECRET in card.privacy_classes or PrivacyClass.SENSITIVE in card.privacy_classes:
        return RiskLevel.HIGH
    if card.side_effect is SideEffect.WRITE or PrivacyClass.PERSONAL in card.privacy_classes:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW

