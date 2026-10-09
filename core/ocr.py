"""OCR engine wrapper. RapidOCR (ONNX, on-device); EasyOCR only as an import fallback. Lazy singleton."""
from dataclasses import dataclass

import numpy as np


@dataclass
class OcrResult:
    text: str  # "" when nothing was read
    confidence: float  # 0..1; 0.0 when nothing was read


def engine_name() -> str:
    """e.g. "rapidocr 3.10.0 (onnxruntime)". Must not trigger model loading."""
    raise NotImplementedError


def warm_up() -> None:
    """Load the models and run one tiny inference so the first real call is fast."""
    raise NotImplementedError


def read_text(image: np.ndarray) -> OcrResult:
    """Read ONE line of text from a BGR crop of a field zone (text plus white margin, any width).
    Several text boxes -> join left-to-right with single spaces; confidence = the lowest box score.
    Thread-safe (the API calls this from a threadpool). Never touches the network."""
    raise NotImplementedError
