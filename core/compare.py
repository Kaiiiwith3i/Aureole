"""Field normalization and the three-state MATCH / MISMATCH / UNREADABLE decision."""
import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

SIM_MATCH = 0.90  # text fields match at or above this similarity
CONF_MIN = 0.80  # below this OCR confidence a non-match is UNREADABLE, never MISMATCH

_NUM_MAP = str.maketrans("OIlSB", "0115" + "8")


@dataclass
class FieldCompare:
    status: str  # "MATCH" | "MISMATCH" | "UNREADABLE"
    similarity: float  # 0..1 on normalized strings


def normalize(text: str, numeric: bool = False) -> str:
    """NFKC, strip diacritics (ñ -> n), casefold, collapse whitespace, drop spaces around punctuation.
    numeric=True additionally maps O->0, I/l->1, S->5, B->8 (applied before casefold) and removes all whitespace."""
    t = unicodedata.normalize("NFKC", text)
    if numeric:
        t = t.translate(_NUM_MAP)
    t = "".join(c for c in unicodedata.normalize("NFD", t) if not unicodedata.combining(c)).casefold()
    if numeric:
        return re.sub(r"\s+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"\s*([^\w\s])\s*", r"\1", t)


def compare_field(signed: str, read: str, confidence: float, numeric: bool = False) -> FieldCompare:
    """similarity = rapidfuzz ratio of the normalized strings (0..1).
    match = exact equality for numeric fields, similarity >= SIM_MATCH otherwise.
    match -> MATCH. Else: empty read or confidence < CONF_MIN -> UNREADABLE. Else MISMATCH."""
    a, b = normalize(signed, numeric), normalize(read, numeric)
    sim = fuzz.ratio(a, b) / 100
    if a == b if numeric else sim >= SIM_MATCH:
        return FieldCompare("MATCH", sim)
    return FieldCompare("UNREADABLE" if not b or confidence < CONF_MIN else "MISMATCH", sim)
