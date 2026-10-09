"""Synthetic tampering and wear, applied in template space BEFORE photo simulation.
Every function returns (new_image, bbox [x, y, w, h] of what it touched) and never modifies its input. Deterministic per seed."""
import numpy as np


def add_stamp(image: np.ndarray, center: tuple[int, int], radius: int = 120, text: str = "RECEIVED", seed: int = 0):
    """Red circular rubber stamp (double ring + text), slightly rotated, semi-transparent."""
    raise NotImplementedError


def add_scribble(image: np.ndarray, bbox: list[int], seed: int = 0):
    """Blue ballpoint handwriting-like strokes inside bbox."""
    raise NotImplementedError


def add_stain(image: np.ndarray, center: tuple[int, int], radius: int = 150, seed: int = 0):
    """Brown coffee ring: darker irregular rim, pale translucent fill. Text underneath stays legible."""
    raise NotImplementedError


def add_fold(image: np.ndarray, position: float = 0.5, vertical: bool = True, seed: int = 0):
    """Fold crease across the whole page at `position` (0..1): a thin dark line with a soft shading band."""
    raise NotImplementedError


def retype_field(image: np.ndarray, key: str, new_value: str):
    """Paint the field zone white and retype new_value in the same font (core.template.draw_field)."""
    raise NotImplementedError


def smudge_field(image: np.ndarray, key: str, seed: int = 0):
    """Heavy blur/smear over one field zone only, strong enough that the value can't be read."""
    raise NotImplementedError


def copy_move(image: np.ndarray, src_bbox: list[int], dst_xy: tuple[int, int]):
    """Copy the src_bbox block to dst_xy (top-left). Returns (image, dst bbox)."""
    raise NotImplementedError


def rogue_reseal(fields: dict[str, str], doc_id: str, version: int = 1) -> np.ndarray:
    """A certificate rendered with a seal signed by a freshly generated key that is NOT in keys/trusted."""
    raise NotImplementedError
