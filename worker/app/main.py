import json
import os
from datetime import datetime
from multiprocessing import Process
from pathlib import Path
from time import sleep

import requests
import websocket
import cv2

from app.capture import ChunkRecorder, CircularFrameBuffer, reconnecting_frames, save_frame
from app.detectors import RuleEngine, ScreenRoi, perceptual_hash


BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
EMAIL = os.getenv("WORKER_EMAIL", os.getenv("ADMIN_EMAIL", "admin@streamwatch.example.com"))
PASSWORD = os.getenv("WORKER_PASSWORD", os.getenv("ADMIN_PASSWORD", "admin123"))
DATA_DIR = Path(os.getenv("STREAMWATCH_DATA_DIR", "./data"))
POLL_SECONDS = int(os.getenv("WORKER_POLL_SECONDS", "10"))
CAPTURE_FPS = int(os.getenv("CAPTURE_FPS", "5"))
CHUNK_SECONDS = int(os.getenv("CHUNK_SECONDS", "60"))
SNAPSHOT_EVERY_SECONDS = int(os.getenv("SNAPSHOT_EVERY_SECONDS", "2"))
STREAM_WS_EVERY_SECONDS = float(os.getenv("STREAM_WS_EVERY_SECONDS", "0.25"))
WORKER_SOURCE_SCOPE = os.getenv("WORKER_SOURCE_SCOPE", "all").lower()
WORKER_DEBUG = os.getenv("WORKER_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on", "debug"}


def debug(message: str) -> None:
    if WORKER_DEBUG:
        print(f"worker_debug {message}", flush=True)


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


def tests(access_token: str) -> list[dict]:
    response = requests.get(f"{BACKEND_URL}/tests", headers=headers(access_token), timeout=10)
    response.raise_for_status()
    return response.json()


def field_test_camera_ids(access_token: str) -> set[int]:
    response = requests.get(f"{BACKEND_URL}/field-tests/cameras", headers=headers(access_token), timeout=10)
    response.raise_for_status()
    return set(response.json().get("camera_ids", []))


def post_event(access_token: str, payload: dict) -> None:
    response = requests.post(f"{BACKEND_URL}/events", json=payload, headers=headers(access_token), timeout=10)
    response.raise_for_status()


def ws_url(access_token: str, camera_id: int) -> str:
    base = BACKEND_URL.replace("https://", "wss://").replace("http://", "ws://")
    return f"{base}/ws/cameras/{camera_id}/stream?mode=producer&token={access_token}"


class FrameStreamer:
    def __init__(self, access_token: str, camera_id: int) -> None:
        self.access_token = access_token
        self.camera_id = camera_id
        self.connection: websocket.WebSocket | None = None

    def send(self, frame) -> None:
        try:
            if self.connection is None or not self.connection.connected:
                self.connection = websocket.create_connection(ws_url(self.access_token, self.camera_id), timeout=2)
            ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            if ok:
                self.connection.send_binary(encoded.tobytes())
        except Exception:
            self.close()

    def close(self) -> None:
        if self.connection is not None:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None


def is_local_source(source: str) -> bool:
    normalized = source.strip().lower()
    return normalized.isdigit() or normalized.startswith("/dev/video") or normalized.startswith("dshow:")


def should_process_camera(camera: dict) -> bool:
    source = str(camera.get("source", ""))
    local = is_local_source(source)
    if WORKER_SOURCE_SCOPE == "local":
        return local
    if WORKER_SOURCE_SCOPE == "network":
        return not local
    return True


def screen_roi(camera: dict) -> ScreenRoi | None:
    values = [camera.get("roi_x"), camera.get("roi_y"), camera.get("roi_width"), camera.get("roi_height")]
    if any(value is None for value in values):
        return None
    x, y, width, height = (float(value) for value in values)
    if width <= 0 or height <= 0:
        return None
    return ScreenRoi(x=x, y=y, width=width, height=height)


def process_camera(access_token: str, camera: dict) -> None:
    engine = RuleEngine(roi=screen_roi(camera))
    buffer = CircularFrameBuffer(max_frames=150)
    chunk_seconds = int(camera.get("chunk_seconds", CHUNK_SECONDS))
    test_id = int(camera["test_id"]) if camera.get("test_id") else None
    should_record = bool(test_id)
    recorder = ChunkRecorder(DATA_DIR, camera_id=camera["id"], fps=CAPTURE_FPS, chunk_seconds=chunk_seconds, test_id=test_id) if should_record else None
    source = camera["source"]
    camera_id = camera["id"]
    last_snapshot_at: datetime | None = None
    last_stream_at: datetime | None = None
    streamer = FrameStreamer(access_token, camera_id)

    try:
        for frame in reconnecting_frames(source, fps=CAPTURE_FPS):
            buffer.add(frame)
            chunk_path = recorder.write(frame) if recorder else None
            now = datetime.utcnow()
            if last_snapshot_at is None or (now - last_snapshot_at).total_seconds() >= SNAPSHOT_EVERY_SECONDS:
                save_frame(frame, DATA_DIR / "snapshots" / f"cam_{camera_id}.jpg")
                last_snapshot_at = now
            if last_stream_at is None or (now - last_stream_at).total_seconds() >= STREAM_WS_EVERY_SECONDS:
                streamer.send(frame)
                last_stream_at = now

            detections = engine.analyze(frame)
            if not detections:
                continue

            timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            for detection in detections:
                evidence_dir = DATA_DIR / "events" / detection.type
                image_path = evidence_dir / f"cam_{camera_id}_{timestamp}.jpg"
                save_frame(frame, image_path)
                metadata = {**detection.metadata, "mode": "recording" if should_record else "field_test"}
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
    processes: dict[int, tuple[Process, int]] = {}
    debug(
        "startup "
        f"backend_url={BACKEND_URL} source_scope={WORKER_SOURCE_SCOPE} "
        f"poll_seconds={POLL_SECONDS} capture_fps={CAPTURE_FPS} chunk_seconds={CHUNK_SECONDS}"
    )
    while True:
        try:
            access_token = token()
            running_tests = [test for test in tests(access_token) if test.get("status") == "running"]
            running_camera_ids = {camera_id for test in running_tests for camera_id in test.get("camera_ids", [])}
            field_camera_ids = field_test_camera_ids(access_token)
            process_camera_ids = running_camera_ids | field_camera_ids
            active = []
            all_cameras = cameras(access_token)
            debug(
                "poll "
                f"tests_running={len(running_tests)} field_test_cameras={sorted(field_camera_ids)} "
                f"processable_ids={sorted(process_camera_ids)} cameras_total={len(all_cameras)}"
            )
            for camera in all_cameras:
                if camera["id"] not in process_camera_ids or not camera.get("enabled") or not should_process_camera(camera):
                    if WORKER_DEBUG:
                        reasons = []
                        if camera["id"] not in process_camera_ids:
                            reasons.append("not_in_running_or_field_test")
                        if not camera.get("enabled"):
                            reasons.append("disabled")
                        if not should_process_camera(camera):
                            reasons.append(f"filtered_by_scope:{WORKER_SOURCE_SCOPE}")
                        debug(
                            f"camera_skip id={camera['id']} name={camera.get('name')} source={camera.get('source')} "
                            f"reasons={','.join(reasons)}"
                        )
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
                debug(
                    f"camera_active id={camera['id']} name={camera.get('name')} source={camera.get('source')} "
                    f"test_id={camera.get('test_id')} field_test={bool(camera.get('field_test'))} "
                    f"chunk_seconds={camera.get('chunk_seconds')}"
                )
            active_ids = {camera["id"] for camera in active}
            if not active:
                debug("no_active_cameras")
                for camera_id, (process, _) in list(processes.items()):
                    debug(f"process_stop id={camera_id} reason=no_active_cameras")
                    process.terminate()
                    process.join(timeout=5)
                    processes.pop(camera_id, None)
                sleep(POLL_SECONDS)
                continue

            for camera_id, (process, chunk_seconds) in list(processes.items()):
                active_camera = next((camera for camera in active if camera["id"] == camera_id), None)
                next_chunk_seconds = int(active_camera.get("chunk_seconds", CHUNK_SECONDS)) if active_camera else CHUNK_SECONDS
                next_test_id = int(active_camera.get("test_id", 0)) if active_camera else 0
                if camera_id not in active_ids or not process.is_alive() or chunk_seconds != next_chunk_seconds or next_test_id != int(getattr(process, "test_id", 0)):
                    debug(
                        f"process_restart id={camera_id} alive={process.is_alive()} "
                        f"chunk_seconds_old={chunk_seconds} chunk_seconds_new={next_chunk_seconds} "
                        f"test_id_old={int(getattr(process, 'test_id', 0))} test_id_new={next_test_id}"
                    )
                    process.terminate()
                    process.join(timeout=5)
                    processes.pop(camera_id, None)

            for camera in active:
                if camera["id"] in processes:
                    continue
                debug(
                    f"process_start id={camera['id']} source={camera.get('source')} "
                    f"test_id={camera.get('test_id', 0)} chunk_seconds={camera.get('chunk_seconds', CHUNK_SECONDS)}"
                )
                process = Process(target=process_camera, args=(access_token, camera), daemon=True)
                process.test_id = int(camera.get("test_id", 0))
                process.start()
                processes[camera["id"]] = (process, int(camera.get("chunk_seconds", CHUNK_SECONDS)))

            sleep(POLL_SECONDS)
        except Exception as exc:
            print(f"worker_error={exc}", flush=True)
            debug("loop_exception traceback_hidden=True")
            sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
