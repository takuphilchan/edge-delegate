"""Small deterministic index over declared capability cards."""

from __future__ import annotations

from dataclasses import dataclass

from edge_delegate.contracts import CapabilityCard

from .lexical import bm25_score, document_frequencies, tokenize


@dataclass(frozen=True, slots=True)
class RetrievedCapability:
    card: CapabilityCard
    score: float
    matched_terms: tuple[str, ...]


class CapabilityIndex:
    """Rank declared cards using bounded, explainable lexical retrieval."""

    def __init__(self, cards: tuple[CapabilityCard, ...]) -> None:
        identifiers = [card.capability_id for card in cards]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("capability identifiers must be unique")
        self._cards = tuple(sorted(cards, key=lambda card: card.capability_id))
        self._tokens = tuple(self._card_tokens(card) for card in self._cards)
        self._document_frequency = document_frequencies(self._tokens)
        self._average_length = (
            sum(map(len, self._tokens)) / len(self._tokens) if self._tokens else 0.0
        )

    @staticmethod
    def _card_tokens(card: CapabilityCard) -> tuple[str, ...]:
        identifier = card.capability_id.replace(".", " ").replace("_", " ").replace("-", " ")
        arguments = " ".join(card.arguments)
        # Repeating the identifier gives stable weight to exact capability vocabulary.
        return tokenize(f"{identifier} {identifier} {card.description} {arguments}")

    def search(
        self,
        query: str,
        *,
        limit: int = 8,
        allowed_ids: frozenset[str] | None = None,
    ) -> tuple[RetrievedCapability, ...]:
        if limit < 1:
            raise ValueError("retrieval limit must be positive")
        query_tokens = tokenize(query)
        ranked: list[RetrievedCapability] = []
        for card, tokens in zip(self._cards, self._tokens, strict=True):
            if allowed_ids is not None and card.capability_id not in allowed_ids:
                continue
            score, matched = bm25_score(
                query_tokens,
                tokens,
                document_frequency=self._document_frequency,
                document_count=len(self._cards),
                average_length=self._average_length,
            )
            if score > 0:
                ranked.append(RetrievedCapability(card=card, score=score, matched_terms=matched))
        ranked.sort(key=lambda item: (-item.score, item.card.capability_id))
        return tuple(ranked[:limit])
