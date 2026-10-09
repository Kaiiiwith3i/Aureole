"""Field normalization and the three-state MATCH / MISMATCH / UNREADABLE decision."""
from dataclasses import dataclass

SIM_MATCH = 0.90  # text fields match at or above this similarity
CONF_MIN = 0.80  # below this OCR confidence a non-match is UNREADABLE, never MISMATCH


@dataclass
class FieldCompare:
    status: str  # "MATCH" | "MISMATCH" | "UNREADABLE"
    similarity: float  # 0..1 on normalized strings


def normalize(text: str, numeric: bool = False) -> str:
    """NFKC, strip diacritics (ñ -> n), casefold, collapse whitespace, drop spaces around punctuation.
    numeric=True additionally maps O->0, I/l->1, S->5, B->8 (applied before casefold) and removes all whitespace."""
    raise NotImplementedError


def compare_field(signed: str, read: str, confidence: float, numeric: bool = False) -> FieldCompare:
    """similarity = rapidfuzz ratio of the normalized strings (0..1).
    match = exact equality for numeric fields, similarity >= SIM_MATCH otherwise.
    match -> MATCH. Else: empty read or confidence < CONF_MIN -> UNREADABLE. Else MISMATCH."""
    raise NotImplementedError
