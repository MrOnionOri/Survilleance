import argparse
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from time import sleep

import cv2

from app.capture import open_capture


@dataclass(frozen=True)
class CameraProbeResult:
    index: int
    source: str
    snapshot_path: Path
    mean_intensity: float


def probe(max_index: int = 5, output_dir: str = "camera_probe") -> list[CameraProbeResult]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    detected: list[CameraProbeResult] = []

    for index in range(max_index + 1):
        capture = open_capture(str(index))
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
        source = str(index)
        detected.append(CameraProbeResult(index=index, source=source, snapshot_path=path, mean_intensity=mean_intensity))
        print(f"camera_{index}=ok source={source} mean_intensity={mean_intensity:.2f} snapshot={path}")

    print_probe_summary(detected)
    return detected


def print_probe_summary(detected: list[CameraProbeResult]) -> None:
    print("")
    print("Resumen de camaras locales")
    print("--------------------------")
    if not detected:
        print("No detecte camaras locales abiertas por OpenCV.")
        if platform.system() == "Darwin":
            print("En macOS revisa System Settings > Privacy & Security > Camera y habilita Terminal, iTerm o VS Code.")
        print("Tambien verifica que otra app no tenga ocupada la camara.")
        return

    for result in detected:
        print(
            f"- Camara indice {result.index}: en el dashboard coloca Fuente = {result.source} "
            f"(snapshot: {result.snapshot_path}, brillo medio: {result.mean_intensity:.2f})"
        )

    print("")
    print("Ejemplos para registrar en Fuentes:")
    for result in detected:
        print(f"  Nombre: Camara {result.index} | Fuente: {result.source}")

    if platform.system() == "Darwin":
        print("")
        print("Tip macOS: si prefieres ser explicito, tambien puedes usar Fuente = avfoundation:<indice>.")
        for result in detected:
            print(f"  Fuente alternativa para camara {result.index}: avfoundation:{result.index}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Probe local camera indexes.")
    parser.add_argument("--max-index", type=int, default=int(os.getenv("CAMERA_PROBE_MAX_INDEX", "5")))
    parser.add_argument("--output-dir", default=os.getenv("CAMERA_PROBE_OUTPUT_DIR", "camera_probe"))
    args = parser.parse_args()
    probe(max_index=args.max_index, output_dir=args.output_dir)
