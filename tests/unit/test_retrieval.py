"""Tests for deterministic capability retrieval."""

from edge_delegate.contracts import CapabilityCard, SideEffect, ValueKind, ValueSpec
from edge_delegate.retrieval import CapabilityIndex, tokenize


def _card(capability_id: str, description: str) -> CapabilityCard:
    return CapabilityCard(
        capability_id=capability_id,
        version="0.1.0",
        description=description,
        arguments={},
        result=ValueSpec(ValueKind.NUMBER),
        side_effect=SideEffect.READ,
    )


def test_tokenize_handles_identifiers_and_unicode() -> None:
    assert tokenize("TEMP_sensor café") == ("temp", "sensor", "café")


def test_capability_index_ranks_relevant_card_and_is_stable() -> None:
    cards = (
        _card("sensor.battery.read", "Read the remaining battery charge percentage."),
        _card("sensor.temperature.read", "Read ambient room temperature in Celsius."),
    )
    index = CapabilityIndex(cards)

    first = index.search("show the room temperature", limit=1)
    second = index.search("show the room temperature", limit=1)

    assert first == second
    assert first[0].card.capability_id == "sensor.temperature.read"
    assert "temperature" in first[0].matched_terms


def test_capability_index_respects_policy_allowlist() -> None:
    cards = (
        _card("sensor.battery.read", "Read battery level."),
        _card("sensor.temperature.read", "Read temperature."),
    )
    result = CapabilityIndex(cards).search(
        "read temperature",
        allowed_ids=frozenset({"sensor.battery.read"}),
    )
    assert tuple(item.card.capability_id for item in result) == ("sensor.battery.read",)
