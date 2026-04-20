import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from multiprocessing import Process
from pathlib import Path
from time import monotonic, sleep

import requests
import websocket
import cv2

from app.capture import ChunkRecorder, CircularFrameBuffer, ffmpeg_exe, reconnecting_frames, save_frame
from app.detectors import RuleEngine, ScreenRoi, perceptual_hash
from app.probe_cameras import probe as probe_local_cameras
from app.transforms import apply_frame_transforms, transform_signature


BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
EMAIL = os.getenv("WORKER_EMAIL", os.getenv("ADMIN_EMAIL", "admin@streamwatch.example.com"))
PASSWORD = os.getenv("WORKER_PASSWORD", os.getenv("ADMIN_PASSWORD", "admin123"))
DATA_DIR = Path(os.getenv("STREAMWATCH_DATA_DIR", "./data"))
POLL_SECONDS = int(os.getenv("WORKER_POLL_SECONDS", "10"))
CAPTURE_FPS = int(os.getenv("CAPTURE_FPS", "5"))
CHUNK_SECONDS = int(os.getenv("CHUNK_SECONDS", "60"))
SNAPSHOT_EVERY_SECONDS = int(os.getenv("SNAPSHOT_EVERY_SECONDS", "2"))
WORKER_SOURCE_SCOPE = os.getenv("WORKER_SOURCE_SCOPE", "all").lower()
WORKER_PRINT_LOCAL_CAMERAS = os.getenv("WORKER_PRINT_LOCAL_CAMERAS", "true").lower() in {"1", "true", "yes", "on"}
WORKER_CAMERA_PROBE_MAX_INDEX = int(os.getenv("WORKER_CAMERA_PROBE_MAX_INDEX", "8"))
EVENT_COOLDOWN_SECONDS = float(os.getenv("EVENT_COOLDOWN_SECONDS", "10"))
CAMERA_SETTINGS_POLL_SECONDS = float(os.getenv("CAMERA_SETTINGS_POLL_SECONDS", "1"))


def token() -> str:
    response = requests.post(
        f"{BACKEND_URL}/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def cameras(access_token: str) -> list[dict]:
    response = requests.get(f"{BACKEND_URL}/cameras", headers=headers(access_token), timeout=10)
    response.raise_for_status()
    return response.json()


def camera_details(access_token: str, camera_id: int) -> dict:
    response = requests.get(f"{BACKEND_URL}/cameras/{camera_id}", headers=headers(access_token), timeout=10)
    response.raise_for_status()
    return response.json()


def tests(access_token: str) -> list[dict]:
    response = requests.get(f"{BACKEND_URL}/tests", headers=headers(access_token), timeout=10)
    response.raise_for_status()
    return response.json()


def field_test_camera_ids(access_token: str) -> set[int]:
    response = requests.get(f"{BACKEND_URL}/field-tests/cameras", headers=headers(access_token), timeout=10)
    response.raise_for_status()
    return set(response.json().get("camera_ids", []))


def post_event(access_token: str, payload: dict) -> bool:
    try:
        response = requests.post(f"{BACKEND_URL}/events", json=payload, headers=headers(access_token), timeout=10)
    except requests.RequestException as exc:
        print(f"event_post_error camera_id={payload.get('camera_id')} type={payload.get('type')} error={exc}", flush=True)
        return False

    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "unknown")
        print(
            f"event_rate_limited camera_id={payload.get('camera_id')} type={payload.get('type')} retry_after={retry_after}",
            flush=True,
        )
        return False

    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = response.text[:240].replace("\n", " ")
        print(
            f"event_post_error camera_id={payload.get('camera_id')} type={payload.get('type')} "
            f"status={response.status_code} detail={detail} error={exc}",
            flush=True,
        )
        return False

    return True


def ws_url(access_token: str, camera_id: int, mode: str = "producer") -> str:
    base = BACKEND_URL.replace("https://", "wss://").replace("http://", "ws://")
    return f"{base}/ws/cameras/{camera_id}/stream?mode={mode}&token={access_token}"


def test_is_running(test: dict) -> bool:
    if test.get("status") != "running":
        return False
    ends_at = test.get("ends_at")
    if not ends_at:
        return True
    try:
        parsed = datetime.fromisoformat(str(ends_at).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed > datetime.now(timezone.utc)
    except ValueError:
        return True


VIDEO_STREAM_MAX_FPS = int(os.getenv("VIDEO_STREAM_MAX_FPS", "15"))
VIDEO_STREAM_MAX_WIDTH = int(os.getenv("VIDEO_STREAM_MAX_WIDTH", "960"))
VIDEO_STREAM_JPEG_FPS = float(os.getenv("VIDEO_STREAM_JPEG_FPS", "5"))


class VideoStreamer:
    def __init__(self, access_token: str, camera_id: int, fps: int) -> None:
        self.access_token = access_token
        self.camera_id = camera_id
        self.fps = max(1, min(fps, VIDEO_STREAM_MAX_FPS))
        self.connection: websocket.WebSocket | None = None
        self.jpeg_connection: websocket.WebSocket | None = None
        self.process: subprocess.Popen | None = None
        self.frame_size: tuple[int, int] | None = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"cam-{camera_id}-video")
        self.last_jpeg_at = 0.0

    def send(self, frame) -> None:
        try:
            frame = self._prepare_frame(frame)
            self._send_jpeg(frame)
            height, width = frame.shape[:2]
            frame_size = (width, height)
            if self.process is None or self.process.poll() is not None or self.frame_size != frame_size:
                self._start(frame_size)
            if self.process is None or self.process.stdin is None:
                return
            self.process.stdin.write(frame.tobytes())
        except Exception:
            self._stop_stream()

    def _send_jpeg(self, frame) -> None:
        if VIDEO_STREAM_JPEG_FPS <= 0:
            return
        now = monotonic()
        if now - self.last_jpeg_at < 1.0 / VIDEO_STREAM_JPEG_FPS:
            return
        try:
            if self.jpeg_connection is None or not self.jpeg_connection.connected:
                self.jpeg_connection = websocket.create_connection(ws_url(self.access_token, self.camera_id, mode="producer_jpeg"), timeout=2)
            ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            if ok:
                self.jpeg_connection.send_binary(encoded.tobytes())
                self.last_jpeg_at = now
        except Exception:
            if self.jpeg_connection is not None:
                try:
                    self.jpeg_connection.close()
                except Exception:
                    pass
            self.jpeg_connection = None

    def _prepare_frame(self, frame):
        height, width = frame.shape[:2]
        if VIDEO_STREAM_MAX_WIDTH > 0 and width > VIDEO_STREAM_MAX_WIDTH:
            next_width = VIDEO_STREAM_MAX_WIDTH
            next_height = max(2, int(height * (next_width / width)))
            next_width -= next_width % 2
            next_height -= next_height % 2
            frame = cv2.resize(frame, (next_width, next_height), interpolation=cv2.INTER_AREA)
        else:
            next_width = width - (width % 2)
            next_height = height - (height % 2)
            if next_width != width or next_height != height:
                frame = frame[:next_height, :next_width]
        return frame

    def close(self) -> None:
        self._stop_stream()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _start(self, frame_size: tuple[int, int]) -> None:
        self._stop_stream()
        ffmpeg = ffmpeg_exe()
        if not ffmpeg:
            print(f"live_video_disabled camera_id={self.camera_id} reason=ffmpeg_unavailable", flush=True)
            return

        self.connection = websocket.create_connection(ws_url(self.access_token, self.camera_id), timeout=2)
        width, height = frame_size
        keyframe_interval = max(1, self.fps)
        command = [
            ffmpeg,
            "-loglevel",
            "error",
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
            "ultrafast",
            "-tune",
            "zerolatency",
            "-profile:v",
            "baseline",
            "-level",
            "3.1",
            "-pix_fmt",
            "yuv420p",
            "-g",
            str(keyframe_interval),
            "-keyint_min",
            str(keyframe_interval),
            "-sc_threshold",
            "0",
            "-f",
            "mp4",
            "-movflags",
            "frag_keyframe+empty_moov+default_base_moof",
            "pipe:1",
        ]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.frame_size = frame_size
        self.executor.submit(self._pump_stdout, self.process, self.connection)

    def _pump_stdout(self, process: subprocess.Popen, connection: websocket.WebSocket) -> None:
        if process.stdout is None:
            return
        try:
            stdout_fd = process.stdout.fileno()
            while True:
                chunk = os.read(stdout_fd, 32768)
                if not chunk:
                    break
                connection.send_binary(chunk)
        except Exception:
            pass

    def _stop_stream(self) -> None:
        if self.process is not None:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
            except Exception:
                pass
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
            self.frame_size = None
        if self.connection is not None:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None
        if self.jpeg_connection is not None:
            try:
                self.jpeg_connection.close()
            except Exception:
                pass
            self.jpeg_connection = None


def is_local_source(source: str) -> bool:
    normalized = source.strip().lower()
    return (
        normalized.isdigit()
        or normalized.startswith("/dev/video")
        or normalized.startswith("dshow:")
        or normalized.startswith("avfoundation:")
    )


def should_process_camera(camera: dict) -> bool:
    source = str(camera.get("source", ""))
    local = is_local_source(source)
    if WORKER_SOURCE_SCOPE == "local":
        return local
    if WORKER_SOURCE_SCOPE == "network":
        return not local
    return True


def print_local_camera_sources() -> None:
    if not WORKER_PRINT_LOCAL_CAMERAS:
        return
    if WORKER_SOURCE_SCOPE == "network":
        return
    print("", flush=True)
    print("Buscando camaras locales disponibles para este worker...", flush=True)
    try:
        probe_local_cameras(
            max_index=WORKER_CAMERA_PROBE_MAX_INDEX,
            output_dir=str(DATA_DIR / "camera_probe"),
        )
    except Exception as exc:
        print(f"No pude escanear camaras locales: {exc}", flush=True)
    print("", flush=True)


def screen_roi(camera: dict) -> ScreenRoi | None:
    values = [camera.get("roi_x"), camera.get("roi_y"), camera.get("roi_width"), camera.get("roi_height")]
    if any(value is None for value in values):
        return None
    x, y, width, height = (float(value) for value in values)
    if width <= 0 or height <= 0:
        return None
    return ScreenRoi(x=x, y=y, width=width, height=height)


def should_emit_detection(last_event_at: dict[str, float], detection_type: str, now: float) -> bool:
    previous = last_event_at.get(detection_type)
    if previous is not None and now - previous < EVENT_COOLDOWN_SECONDS:
        return False
    last_event_at[detection_type] = now
    return True


def process_camera(access_token: str, camera: dict) -> None:
    engine = RuleEngine(roi=screen_roi(camera))
    buffer = CircularFrameBuffer(max_frames=150)
    capture_fps = int(camera.get("capture_fps") or CAPTURE_FPS)
    chunk_seconds = int(camera.get("chunk_seconds", CHUNK_SECONDS))
    test_id = int(camera["test_id"]) if camera.get("test_id") else None
    should_record = bool(test_id)
    recorder = ChunkRecorder(DATA_DIR, camera_id=camera["id"], fps=capture_fps, chunk_seconds=chunk_seconds, test_id=test_id) if should_record else None
    source = camera["source"]
    camera_id = camera["id"]
    last_snapshot_at: datetime | None = None
    last_stream_at: datetime | None = None
    last_event_at: dict[str, float] = {}
    recording_disabled = False
    camera_settings = dict(camera)
    current_signature = transform_signature(camera_settings)
    last_settings_at = monotonic()
    streamer = VideoStreamer(access_token, camera_id, fps=capture_fps)

    try:
        for raw_frame in reconnecting_frames(source, fps=capture_fps):
            now_monotonic = monotonic()
            if now_monotonic - last_settings_at >= CAMERA_SETTINGS_POLL_SECONDS:
                try:
                    updated_camera = camera_details(access_token, camera_id)
                    next_signature = transform_signature(updated_camera)
                    camera_settings = updated_camera
                    if next_signature != current_signature:
                        engine.roi = screen_roi(camera_settings)
                        engine.reset_history()
                        current_signature = next_signature
                except Exception as exc:
                    print(f"camera_settings_refresh_error camera_id={camera_id} error={exc}", flush=True)
                last_settings_at = now_monotonic

            frame = apply_frame_transforms(raw_frame, camera_settings)
            buffer.add(frame)
            chunk_path = None
            if recorder:
                try:
                    chunk_path = recorder.write(frame)
                except RuntimeError as exc:
                    print(
                        f"recording_disabled camera_id={camera_id} reason={exc}",
                        flush=True,
                    )
                    recorder.close()
                    recorder = None
                    recording_disabled = True
            now = datetime.utcnow()
            if last_snapshot_at is None or (now - last_snapshot_at).total_seconds() >= SNAPSHOT_EVERY_SECONDS:
                save_frame(frame, DATA_DIR / "snapshots" / f"cam_{camera_id}.jpg")
                last_snapshot_at = now
            if last_stream_at is None or (now - last_stream_at).total_seconds() >= 1 / max(streamer.fps, 1):
                streamer.send(frame)
                last_stream_at = now

            detections = engine.analyze(frame)
            if not detections:
                continue

            timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            for detection in detections:
                if not should_emit_detection(last_event_at, detection.type, monotonic()):
                    continue
                evidence_dir = DATA_DIR / "events" / detection.type
                image_path = evidence_dir / f"cam_{camera_id}_{timestamp}.jpg"
                save_frame(frame, image_path)
                metadata = {
                    **detection.metadata,
                    "mode": "recording" if should_record and not recording_disabled else "field_test",
                    "event_cooldown_seconds": EVENT_COOLDOWN_SECONDS,
                }
                if recording_disabled:
                    metadata["recording_disabled"] = "ffmpeg_unavailable"
                if chunk_path:
                    metadata["recording_path"] = str(chunk_path)
                payload = {
                    "camera_id": camera_id,
                    "type": detection.type,
                    "confidence": detection.confidence,
                    "image_path": str(image_path),
                    "clip_path": str(chunk_path) if chunk_path else None,
                    "ad_fingerprint": perceptual_hash(frame) if detection.type in {"scene_change", "ad"} else None,
                    "metadata_json": json.dumps(metadata),
                }
                post_event(access_token, payload)
    finally:
        streamer.close()
        if recorder:
            recorder.close()


def main() -> None:
    print_local_camera_sources()
    processes: dict[int, tuple[Process, int, int]] = {}
    while True:
        try:
            access_token = token()
            running_tests = [test for test in tests(access_token) if test_is_running(test)]
            running_camera_ids = {camera_id for test in running_tests for camera_id in test.get("camera_ids", [])}
            field_camera_ids = field_test_camera_ids(access_token)
            process_camera_ids = running_camera_ids | field_camera_ids
            active = []
            for camera in cameras(access_token):
                if camera["id"] not in process_camera_ids or not camera.get("enabled") or not should_process_camera(camera):
                    continue
                matching_tests = [test for test in running_tests if camera["id"] in test.get("camera_ids", [])]
                if matching_tests:
                    latest_test = sorted(matching_tests, key=lambda test: test["started_at"])[-1]
                    camera["test_id"] = latest_test["id"]
                    camera["chunk_seconds"] = int(latest_test.get("chunk_seconds", CHUNK_SECONDS))
                elif camera["id"] in field_camera_ids:
                    camera["field_test"] = True
                    camera["chunk_seconds"] = int(camera.get("chunk_seconds", CHUNK_SECONDS))
                active.append(camera)
            active_ids = {camera["id"] for camera in active}
            if not active:
                for camera_id, (process, _, _) in list(processes.items()):
                    process.terminate()
                    process.join(timeout=5)
                    processes.pop(camera_id, None)
                sleep(POLL_SECONDS)
                continue

            for camera_id, (process, chunk_seconds, capture_fps) in list(processes.items()):
                active_camera = next((camera for camera in active if camera["id"] == camera_id), None)
                next_chunk_seconds = int(active_camera.get("chunk_seconds", CHUNK_SECONDS)) if active_camera else CHUNK_SECONDS
                next_capture_fps = int(active_camera.get("capture_fps") or CAPTURE_FPS) if active_camera else CAPTURE_FPS
                next_test_id = int(active_camera.get("test_id", 0)) if active_camera else 0
                if (
                    camera_id not in active_ids
                    or not process.is_alive()
                    or chunk_seconds != next_chunk_seconds
                    or capture_fps != next_capture_fps
                    or next_test_id != int(getattr(process, "test_id", 0))
                ):
                    process.terminate()
                    process.join(timeout=5)
                    processes.pop(camera_id, None)

            for camera in active:
                if camera["id"] in processes:
                    continue
                process = Process(target=process_camera, args=(access_token, camera), daemon=True)
                process.test_id = int(camera.get("test_id", 0))
                process.start()
                processes[camera["id"]] = (
                    process,
                    int(camera.get("chunk_seconds", CHUNK_SECONDS)),
                    int(camera.get("capture_fps") or CAPTURE_FPS),
                )

            sleep(POLL_SECONDS)
        except Exception as exc:
            print(f"worker_error={exc}", flush=True)
            sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
