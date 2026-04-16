import os
from pathlib import Path
from time import sleep

# Reduce noisy OpenCV backend logs (e.g., obsensor index out of range).
os.environ.setdefault("OPENCV_LOG_LEVEL", "FATAL")

import cv2


def open_index(index: int) -> cv2.VideoCapture:
    if os.name == "nt":
        capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if capture.isOpened():
            return capture
        capture.release()
    return cv2.VideoCapture(index)


def probe(max_index: int = 5, output_dir: str = "camera_probe") -> None:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)

    for index in range(max_index + 1):
        capture = open_index(index)
        if not capture.isOpened():
            print(f"camera_{index}=not_available")
            continue

        # Warm up auto exposure; first frames can be black.
        frame = None
        for _ in range(20):
            ok, frame = capture.read()
            if not ok:
                frame = None
                break
            sleep(0.05)

        capture.release()
        if frame is None:
            print(f"camera_{index}=no_frame")
            continue

        mean_intensity = float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean())
        path = root / f"camera_{index}.jpg"
        cv2.imwrite(str(path), frame)
        print(f"camera_{index}=ok mean_intensity={mean_intensity:.2f} snapshot={path}")


if __name__ == "__main__":
    probe()
