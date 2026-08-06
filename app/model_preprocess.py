"""Runtime image transforms declared by ONNX model metadata.

Kept inside ``app`` so Vercel's Python file tracer always bundles it. Training imports
the equivalent registry from ``bench/preprocess.py``.
"""

from __future__ import annotations

from functools import partial

import cv2
import numpy as np


def clahe(img, clip=2.0, tile=8):
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lab[..., 0] = cv2.createCLAHE(clip, (tile, tile)).apply(lab[..., 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def flatten(img, sigma=31):
    bg = cv2.GaussianBlur(img, (0, 0), sigma).astype(np.float32)
    return np.clip(img / np.maximum(bg, 1.0) * 128.0, 0, 255).astype(np.uint8)


def blackhat(img, k=9, gain=1.0):
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    residual = cv2.morphologyEx(img, cv2.MORPH_BLACKHAT, se).astype(np.int16)
    return np.clip(img - gain * residual, 0, 255).astype(np.uint8)


def tophat(img, k=9, gain=1.0):
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    residual = cv2.morphologyEx(img, cv2.MORPH_TOPHAT, se).astype(np.int16)
    return np.clip(img + gain * residual, 0, 255).astype(np.uint8)


def bothat(img, k=9, gain=1.0):
    return tophat(blackhat(img, k, gain), k, gain)


def unsharp(img, sigma=2.0, amount=1.0):
    blur = cv2.GaussianBlur(img, (0, 0), sigma)
    return cv2.addWeighted(img, 1 + amount, blur, -amount, 0)


def gamma(img, g=0.7):
    lut = np.clip((np.arange(256) / 255.0) ** g * 255.0, 0, 255).astype(np.uint8)
    return cv2.LUT(img, lut)


def chain(*names):
    functions = [OPS[name] for name in names]

    def run(img):
        for function in functions:
            img = function(img)
        return img

    return run


OPS = {
    "none": lambda img: img,
    "clahe2": partial(clahe, clip=2.0),
    "clahe4": partial(clahe, clip=4.0),
    "flatten": flatten,
    "blackhat": blackhat,
    "tophat": tophat,
    "bothat": bothat,
    "unsharp": unsharp,
    "unsharp_soft": partial(unsharp, sigma=1.5, amount=0.5),
    "gamma07": partial(gamma, g=0.7),
    "gamma13": partial(gamma, g=1.3),
    "median3": lambda img: cv2.medianBlur(img, 3),
    "median5": lambda img: cv2.medianBlur(img, 5),
    "bilateral": lambda img: cv2.bilateralFilter(img, 5, 50, 50),
    "bilateral_hard": lambda img: cv2.bilateralFilter(img, 7, 75, 75),
    "gauss1": lambda img: cv2.GaussianBlur(img, (0, 0), 1.0),
    "nlmeans": lambda img: cv2.fastNlMeansDenoisingColored(img, None, 3, 3, 7, 21),
}


def build(spec: str):
    return chain(*spec.split("+"))
