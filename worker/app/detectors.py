from dataclasses import dataclass

import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim


@dataclass(frozen=True)
class DetectorConfig:
    black_threshold: float = 18.0
    freeze_ssim_threshold: float = 0.98
    freeze_frames: int = 15
    scene_hist_threshold: float = 0.45
    phash_size: int = 8


@dataclass
class Detection:
    type: str
    confidence: float
    metadata: dict[str, float | int | str]


@dataclass(frozen=True)
class ScreenRoi:
    x: float
    y: float
    width: float
    height: float


class RuleEngine:
    def __init__(self, config: DetectorConfig | None = None, roi: ScreenRoi | None = None) -> None:
        self.config = config or DetectorConfig()
        self.roi = roi
        self.previous_gray: np.ndarray | None = None
        self.previous_hist: np.ndarray | None = None
        self.freeze_count = 0

    def analyze(self, frame: np.ndarray) -> list[Detection]:
        analysis_frame = self._crop(frame)
        gray = cv2.cvtColor(analysis_frame, cv2.COLOR_BGR2GRAY)
        detections: list[Detection] = []
        base_metadata = self._roi_metadata(frame)

        mean_intensity = float(gray.mean())
        if mean_intensity < self.config.black_threshold:
            detections.append(
                Detection(
                    type="black_screen",
                    confidence=min(1.0, (self.config.black_threshold - mean_intensity) / self.config.black_threshold),
                    metadata={**base_metadata, "mean_intensity": mean_intensity},
                )
            )

        if self.previous_gray is not None:
            score = float(ssim(self.previous_gray, gray))
            if score > self.config.freeze_ssim_threshold:
                self.freeze_count += 1
            else:
                self.freeze_count = 0

            if self.freeze_count >= self.config.freeze_frames:
                detections.append(
                    Detection(
                        type="freeze",
                        confidence=min(1.0, score),
                        metadata={**base_metadata, "ssim": score, "frames": self.freeze_count},
                    )
                )

        hist = self._histogram(analysis_frame)
        if self.previous_hist is not None:
            distance = float(cv2.compareHist(self.previous_hist, hist, cv2.HISTCMP_BHATTACHARYYA))
            if distance > self.config.scene_hist_threshold:
                detections.append(
                    Detection(
                        type="scene_change",
                        confidence=min(1.0, distance),
                        metadata={**base_metadata, "histogram_distance": distance},
                    )
                )

        self.previous_gray = gray
        self.previous_hist = hist
        return detections

    def _crop(self, frame: np.ndarray) -> np.ndarray:
        if self.roi is None:
            return frame
        height, width = frame.shape[:2]
        x1 = max(0, min(width - 1, int(self.roi.x * width)))
        y1 = max(0, min(height - 1, int(self.roi.y * height)))
        x2 = max(x1 + 1, min(width, int((self.roi.x + self.roi.width) * width)))
        y2 = max(y1 + 1, min(height, int((self.roi.y + self.roi.height) * height)))
        return frame[y1:y2, x1:x2]

    def _roi_metadata(self, frame: np.ndarray) -> dict[str, float | int | str]:
        if self.roi is None:
            return {"analysis_region": "full_frame"}
        height, width = frame.shape[:2]
        return {
            "analysis_region": "screen_roi",
            "roi_x": self.roi.x,
            "roi_y": self.roi.y,
            "roi_width": self.roi.width,
            "roi_height": self.roi.height,
            "frame_width": width,
            "frame_height": height,
        }

    @staticmethod
    def _histogram(frame: np.ndarray) -> np.ndarray:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        return hist


def perceptual_hash(frame: np.ndarray, size: int = 8) -> str:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(resized))
    low_freq = dct[:size, :size]
    median = np.median(low_freq[1:, 1:])
    bits = low_freq > median
    return "".join("1" if bit else "0" for bit in bits.flatten())
