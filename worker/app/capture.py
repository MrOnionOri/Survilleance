from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
import os
from pathlib import Path
import platform
import shutil
import subprocess
from time import monotonic, sleep

import cv2
import imageio_ffmpeg
import numpy as np


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
    normalized = source.strip().lower()
    if normalized.isdigit():
        return open_camera_index(int(normalized))
    if normalized.startswith("avfoundation:"):
        return open_camera_index(int(normalized.split(":", 1)[1]))

    capture = cv2.VideoCapture(source)
    return capture


def open_camera_index(index: int) -> cv2.VideoCapture:
    if platform.system() == "Darwin":
        capture = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
        if capture.isOpened():
            return capture
    return cv2.VideoCapture(index)


def save_frame(frame: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), frame)


def ffmpeg_exe() -> str | None:
    configured = os.getenv("IMAGEIO_FFMPEG_EXE")
    if configured and Path(configured).exists():
        return configured
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except RuntimeError:
        return shutil.which("ffmpeg")


class ChunkRecorder:
    def __init__(self, root: Path, camera_id: int, fps: int = 5, chunk_seconds: int = 60, test_id: int | None = None) -> None:
        self.root = root
        self.camera_id = camera_id
        self.test_id = test_id
        self.fps = max(1, int(fps))
        self.chunk_seconds = chunk_seconds
        self.process: subprocess.Popen | None = None
        self.started_at: datetime | None = None
        self.started_monotonic: float | None = None
        self.frame_size: tuple[int, int] | None = None
        self.frames_written = 0

    def write(self, frame: np.ndarray) -> Path:
        now = datetime.utcnow()
        now_monotonic = monotonic()
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
            self._rotate(frame, now, now_monotonic)
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("FFmpeg writer could not be initialized")
        self._write_due_frames(frame, now_monotonic)
        return self._path_for(self.started_at or now)

    def close(self) -> None:
        if self.process is not None:
            if self.process.stdin:
                try:
                    self.process.stdin.close()
                except BrokenPipeError:
                    pass
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
            self.process = None

    def _rotate(self, frame: np.ndarray, started_at: datetime, started_monotonic: float) -> None:
        self.close()
        path = self._path_for(started_at)
        path.parent.mkdir(parents=True, exist_ok=True)
        height, width = frame.shape[:2]
        self.frame_size = (width, height)
        ffmpeg = ffmpeg_exe()
        if not ffmpeg:
            raise RuntimeError(
                "No ffmpeg executable found. Install ffmpeg or set IMAGEIO_FFMPEG_EXE to its path."
            )
        command = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{width}x{height}",
            "-framerate",
            str(self.fps),
            "-i",
            "-",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-profile:v",
            "baseline",
            "-g",
            str(max(1, self.fps * 2)),
            "-keyint_min",
            str(max(1, self.fps * 2)),
            "-sc_threshold",
            "0",
            "-r",
            str(self.fps),
            "-vsync",
            "cfr",
            "-pix_fmt",
            "yuv420p",
            "-video_track_timescale",
            str(self.fps * 1000),
            "-movflags",
            "+faststart",
            str(path),
        ]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.started_at = started_at
        self.started_monotonic = started_monotonic
        self.frames_written = 0

    def _write_due_frames(self, frame: np.ndarray, now: float) -> None:
        if self.process is None or self.process.stdin is None:
            return
        if self.started_monotonic is None:
            self.started_monotonic = now
        elapsed = max(0.0, now - self.started_monotonic)
        target_frames = int(elapsed * self.fps) + 1
        due_frames = max(1, target_frames - self.frames_written)
        due_frames = min(due_frames, max(1, self.fps))
        frame_bytes = frame.tobytes()
        for _ in range(due_frames):
            self.process.stdin.write(frame_bytes)
            self.frames_written += 1

    def _path_for(self, started_at: datetime) -> Path:
        date_dir = started_at.strftime("%Y-%m-%d")
        filename = started_at.strftime("%H-%M-%S.mp4")
        if self.test_id is not None:
            return self.root / "recordings" / f"test_{self.test_id}" / f"cam_{self.camera_id}" / date_dir / filename
        return self.root / "recordings" / "unassigned" / f"cam_{self.camera_id}" / date_dir / filename


def reconnecting_frames(source: str, fps: int = 5):
    delay = 1 / max(fps, 1)
    while True:
        capture = open_capture(source)
        if not capture.isOpened():
            sleep(3)
            continue

        next_frame_at = monotonic()
        while True:
            ok, frame = capture.read()
            if not ok:
                capture.release()
                sleep(3)
                break
            yield frame
            next_frame_at += delay
            sleep_for = next_frame_at - monotonic()
            if sleep_for > 0:
                sleep(sleep_for)
            elif sleep_for < -delay:
                next_frame_at = monotonic()
