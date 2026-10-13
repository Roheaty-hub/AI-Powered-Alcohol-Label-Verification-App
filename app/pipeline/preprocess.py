"""Image preprocessing to cope with real-world photos (Jenny's request).

Everything here is classical OpenCV — fast (tens of ms) and fully offline.
"""
from __future__ import annotations

import cv2
import numpy as np

MAX_SIDE = 2000   # px; larger images are slower to OCR with no accuracy gain
MIN_SIDE = 1100   # px; small images are upscaled so small print (the warning) is legible
MAX_DESKEW_DEG = 20


class ImageDecodeError(ValueError):
    pass


def decode(image_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ImageDecodeError("That file isn't a readable image. Please upload a JPG or PNG.")
    return img


def resize(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    long_side = max(h, w)
    if long_side > MAX_SIDE:
        scale = MAX_SIDE / long_side
    elif long_side < MIN_SIDE:
        scale = MIN_SIDE / long_side
    else:
        return img
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    return cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=interp)


def estimate_skew(gray: np.ndarray) -> float:
    """Estimate text rotation in degrees from dominant near-horizontal line segments."""
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 360, threshold=120,
                            minLineLength=gray.shape[1] // 6, maxLineGap=12)
    if lines is None:
        return 0.0
    angles = []
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):  # shape differs across OpenCV versions
        ang = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(ang) <= MAX_DESKEW_DEG:
            angles.append(ang)
    if len(angles) < 3:
        return 0.0
    return float(np.median(angles))


def rotate(img: np.ndarray, angle: float) -> np.ndarray:
    if abs(angle) < 0.3:
        return img
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    border = int(np.median(img[0:5, :])) if img.ndim == 2 else (255, 255, 255)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=border)


def base_gray(image_bytes: bytes) -> tuple[np.ndarray, float]:
    """Decode, resize, grayscale and deskew. Returns (gray image, applied rotation in degrees)."""
    img = resize(decode(image_bytes))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    angle = estimate_skew(gray)
    return rotate(gray, angle), angle


def variant_contrast(gray: np.ndarray) -> np.ndarray:
    """Local contrast equalization — evens out dim lighting and mild glare."""
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def variant_threshold(gray: np.ndarray) -> np.ndarray:
    """Flatten uneven illumination (strong glare / shadows), then adaptive-threshold."""
    background = cv2.medianBlur(gray, 41)
    flat = cv2.divide(gray, background, scale=255)
    flat = cv2.fastNlMeansDenoising(flat, h=12)
    return cv2.adaptiveThreshold(flat, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)
