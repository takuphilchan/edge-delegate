"""Dependency-free tokenization and BM25 scoring for capability retrieval."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping

TOKEN_PATTERN = re.compile(r"[^\W_]+", flags=re.UNICODE)


def tokenize(text: str) -> tuple[str, ...]:
    """Return stable, lowercase Unicode word tokens."""

    return tuple(match.group(0).casefold() for match in TOKEN_PATTERN.finditer(text))


def document_frequencies(documents: Iterable[Iterable[str]]) -> Counter[str]:
    frequencies: Counter[str] = Counter()
    for document in documents:
        frequencies.update(set(document))
    return frequencies


def bm25_score(
    query_tokens: Iterable[str],
    document_tokens: Iterable[str],
    *,
    document_frequency: Mapping[str, int],
    document_count: int,
    average_length: float,
    k1: float = 1.2,
    b: float = 0.75,
) -> tuple[float, tuple[str, ...]]:
    """Score one document and return both score and matched query terms."""

    terms = tuple(document_tokens)
    counts = Counter(terms)
    matched = tuple(sorted(set(query_tokens) & counts.keys()))
    if not matched or document_count <= 0:
        return 0.0, ()
    normalized_length = len(terms) / average_length if average_length else 1.0
    score = 0.0
    for token in matched:
        frequency = counts[token]
        seen_in = document_frequency.get(token, 0)
        inverse_frequency = math.log(1 + (document_count - seen_in + 0.5) / (seen_in + 0.5))
        denominator = frequency + k1 * (1 - b + b * normalized_length)
        score += inverse_frequency * (frequency * (k1 + 1) / denominator)
    return score, matched
