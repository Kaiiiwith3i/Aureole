"""Image forensics that need no seal: Error Level Analysis and copy-move detection."""
from dataclasses import dataclass

import numpy as np


@dataclass
class CopyMoveHit:
    src: tuple[int, int, int, int]  # x, y, w, h (input px)
    dst: tuple[int, int, int, int]
    shift: tuple[int, int]  # dx, dy from src to dst
    blocks: int  # matched blocks sharing this shift
    confidence: float  # 0..1


def ela(image: np.ndarray, quality: int = 90) -> np.ndarray:
    """Gray uint8 map, same HxW: |image - JPEG(image, quality)| max over channels, amplified to use the 0..255 range."""
    raise NotImplementedError


def heatmap(gray: np.ndarray) -> np.ndarray:
    """BGR colormap rendering of an ELA map for the UI."""
    raise NotImplementedError


def copy_move(image: np.ndarray) -> list[CopyMoveHit]:
    """Block matching on overlapping blocks with robust (JPEG-tolerant) features. Flat/blank blocks are skipped.
    Only report a cluster of many blocks sharing the same shift vector (and a shift longer than the block size),
    so naturally repeated glyphs don't trigger it. Must run in < 1.5 s on a 2339x1654 page (downscale internally)."""
    raise NotImplementedError
