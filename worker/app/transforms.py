from __future__ import annotations

import cv2
import numpy as np


def apply_frame_transforms(frame: np.ndarray, camera: dict) -> np.ndarray:
    transformed = frame
    rotation = int(camera.get("rotation_degrees") or 0)
    if rotation == 90:
        transformed = cv2.rotate(transformed, cv2.ROTATE_90_CLOCKWISE)
    elif rotation == 180:
        transformed = cv2.rotate(transformed, cv2.ROTATE_180)
    elif rotation == 270:
        transformed = cv2.rotate(transformed, cv2.ROTATE_90_COUNTERCLOCKWISE)

    if camera.get("flip_horizontal"):
        transformed = cv2.flip(transformed, 1)
    if camera.get("flip_vertical"):
        transformed = cv2.flip(transformed, 0)

    contrast = float(camera.get("digital_contrast") or 1.0)
    brightness = int(camera.get("digital_brightness") or 0)
    if contrast != 1.0 or brightness != 0:
        transformed = np.clip(transformed.astype(np.float32) * contrast + brightness, 0, 255).astype(np.uint8)

    gamma = float(camera.get("digital_gamma") or 1.0)
    if gamma != 1.0:
        inverse_gamma = 1.0 / max(gamma, 0.01)
        table = np.array([((index / 255.0) ** inverse_gamma) * 255 for index in range(256)]).astype("uint8")
        transformed = cv2.LUT(transformed, table)

    return transformed


def transform_signature(camera: dict) -> tuple:
    return (
        int(camera.get("rotation_degrees") or 0),
        bool(camera.get("flip_horizontal")),
        bool(camera.get("flip_vertical")),
        int(camera.get("digital_brightness") or 0),
        round(float(camera.get("digital_contrast") or 1.0), 3),
        round(float(camera.get("digital_gamma") or 1.0), 3),
        camera.get("roi_x"),
        camera.get("roi_y"),
        camera.get("roi_width"),
        camera.get("roi_height"),
    )
