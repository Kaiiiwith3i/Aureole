"""Phone-photo simulation for demo/test/training data. Deterministic per seed."""
import numpy as np


def simulate_photo(image: np.ndarray, seed: int = 0, strength: float = 1.0) -> np.ndarray:
    """BGR page -> BGR "photo": page perspective-warped onto a slightly larger dark desk background (whole page and all
    4 markers stay in frame), lighting gradient, mild warm tint, sensor noise, slight blur. Long side <= 3000 px.
    strength scales every effect (0 = identity apart from the canvas). The caller saves it as JPEG q75."""
    raise NotImplementedError


def save_jpeg(image: np.ndarray, path, quality: int = 75) -> None:
    raise NotImplementedError
