"""Error Level Analysis for the report image layer."""
import cv2
import numpy as np


def ela(image: np.ndarray, quality: int = 90) -> np.ndarray:
    """Gray uint8 map, same HxW: |image - JPEG(image, quality)| max over channels, amplified to use the 0..255 range."""
    re = cv2.imdecode(cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])[1], cv2.IMREAD_COLOR)
    b, g, r = cv2.split(cv2.absdiff(image, re))
    d = cv2.max(cv2.max(b, g), r)
    # ponytail: scale is per-image (99.5th percentile -> 255), so maps are comparable within an image, not across images
    top = max(float(np.percentile(d[::4, ::4], 99.5)), 4.0)
    return cv2.convertScaleAbs(d, alpha=255.0 / top)


def heatmap(gray: np.ndarray) -> np.ndarray:
    """BGR colormap rendering of an ELA map for the UI."""
    return cv2.applyColorMap(gray, cv2.COLORMAP_JET)
