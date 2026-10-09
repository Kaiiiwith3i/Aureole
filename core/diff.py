"""Visual diff: expected render vs aligned scan -> change regions (both template size)."""
from dataclasses import dataclass

import numpy as np


@dataclass
class Region:
    bbox: tuple[int, int, int, int]  # x, y, w, h in template px
    mask: np.ndarray  # uint8 (h, w), 255 where changed, cropped to bbox
    area: int  # changed pixels
    added: float  # 0..1 share of changed pixels that are ink present in the scan but not expected (rest = expected ink missing)


def diff_regions(expected: np.ndarray, aligned: np.ndarray, ignore: list[list[int]] | None = None) -> list[Region]:
    """Both BGR, same size. Steps: grayscale -> illumination normalization (divide by a heavy blur) -> binarize both ->
    dilate each ink mask a few px to absorb misalignment -> added = scan ink not near expected ink, removed = expected ink
    not near scan ink -> also catch colored marks on what should be blank paper (saturation) -> morphology to merge nearby
    pieces -> connected components above a minimum area. `ignore` bboxes (markers, QR box) are zeroed out.
    A clean phone photo (perspective-corrected, JPEG q75, mild noise/blur, lighting gradient) should yield no or only tiny regions.
    Largest regions first; cap at 40."""
    raise NotImplementedError


def diff_overlay(aligned: np.ndarray, regions: list[Region]) -> np.ndarray:
    """Copy of aligned with every region's changed pixels tinted red, for the UI's "Differences" layer."""
    raise NotImplementedError
