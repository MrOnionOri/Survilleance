from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
import logging
import os
from pathlib import Path
import subprocess
from time import sleep

import cv2
import imageio_ffmpeg
import numpy as np

logger = logging.getLogger("streamwatch.worker.capture")
WORKER_DEBUG = os.getenv("WORKER_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on", "debug"}


def debug(message: str) -> None:
    if WORKER_DEBUG:
        logger.info("debug_capture %s", message)


@dataclass
class CircularFrameBuffer:
    max_frames: int
    frames: deque[np.ndarray] = field(init=False)

    def __post_init__(self) -> None:
        self.frames = deque(maxlen=self.max_frames)

    def add(self, frame: np.ndarray) -> None:
        self.frames.append(frame.copy())

    def snapshot(self) -> list[np.ndarray]:
        return list(self.frames)


def open_capture(source: str) -> cv2.VideoCapture:
    debug(f"open_attempt source={source!r} strategy=direct")
    capture = cv2.VideoCapture(source)
    if capture.isOpened():
        debug(f"open_ok source={source!r} strategy=direct")
        return capture
    debug(f"open_failed source={source!r} strategy=direct")
    if source.isdigit():
        index = int(source)
        if os.name == "nt":
            capture.release()
            debug(f"open_attempt source={source!r} strategy=windows_dshow index={index}")
            capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if capture.isOpened():
                debug(f"open_ok source={source!r} strategy=windows_dshow index={index}")
                return capture
            debug(f"open_failed source={source!r} strategy=windows_dshow index={index}")
        capture.release()
        debug(f"open_attempt source={source!r} strategy=index_fallback index={index}")
        return cv2.VideoCapture(index)
    return capture


def save_frame(frame: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), frame)


class ChunkRecorder:
    def __init__(self, root: Path, camera_id: int, fps: int = 5, chunk_seconds: int = 60, test_id: int | None = None) -> None:
        self.root = root
        self.camera_id = camera_id
        self.test_id = test_id
        self.fps = fps
        self.chunk_seconds = chunk_seconds
        self.process: subprocess.Popen | None = None
        self.started_at: datetime | None = None
        self.frame_size: tuple[int, int] | None = None

    def write(self, frame: np.ndarray) -> Path:
        now = datetime.utcnow()
        height, width = frame.shape[:2]
        frame_size = (width, height)
        should_rotate = (
            self.process is None
            or self.started_at is None
            or self.process.poll() is not None
            or self.frame_size != frame_size
            or (now - self.started_at).total_seconds() >= self.chunk_seconds
        )
        if should_rotate:
            self._rotate(frame, now)
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("FFmpeg writer could not be initialized")
        self.process.stdin.write(frame.tobytes())
        return self._path_for(self.started_at or now)

    def close(self) -> None:
        if self.process is not None:
            if self.process.stdin:
                self.process.stdin.close()
            self.process.wait(timeout=10)
            self.process = None

    def _rotate(self, frame: np.ndarray, started_at: datetime) -> None:
        self.close()
        path = self._path_for(started_at)
        path.parent.mkdir(parents=True, exist_ok=True)
        height, width = frame.shape[:2]
        self.frame_size = (width, height)
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        command = [
            ffmpeg,
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{width}x{height}",
            "-r",
            str(self.fps),
            "-i",
            "-",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(path),
        ]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.started_at = started_at

    def _path_for(self, started_at: datetime) -> Path:
        date_dir = started_at.strftime("%Y-%m-%d")
        filename = started_at.strftime("%H-%M-%S.mp4")
        if self.test_id is not None:
            return self.root / "recordings" / f"test_{self.test_id}" / f"cam_{self.camera_id}" / date_dir / filename
        return self.root / "recordings" / "unassigned" / f"cam_{self.camera_id}" / date_dir / filename


def reconnecting_frames(source: str, fps: int = 5):
    delay = 1 / max(fps, 1)
    attempt = 0
    while True:
        attempt += 1
        capture = open_capture(source)
        if not capture.isOpened():
            debug(f"reconnect_wait source={source!r} attempt={attempt} reason=open_failed sleep_s=3")
            sleep(3)
            continue

        debug(f"stream_started source={source!r} attempt={attempt}")
        frame_failures = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                frame_failures += 1
                debug(f"frame_read_failed source={source!r} failures={frame_failures} action=reopen")
                capture.release()
                sleep(3)
                break
            yield frame
            sleep(delay)
