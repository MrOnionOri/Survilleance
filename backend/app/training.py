from __future__ import annotations

import json
import random
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TrainingEvent:
    id: int
    label: str
    image_path: str | None
    metadata_json: str | None = None


@dataclass(frozen=True)
class TrainingResult:
    artifact_path: Path
    model_path: Path
    labels_path: Path
    metrics_path: Path
    manifest_path: Path
    dataset_summary: dict[str, Any]
    metrics: dict[str, Any]


class TrainingError(RuntimeError):
    pass


def train_image_classifier(
    *,
    events: list[TrainingEvent],
    data_dir: Path,
    artifact_path: Path,
    version: str,
    purpose: str,
    epochs: int,
    notes: str | None = None,
    image_size: int = 128,
    min_samples_per_class: int = 1,
) -> TrainingResult:
    try:
        import torch
        from PIL import Image, ImageOps
        from torch import nn
        from torch.utils.data import DataLoader
    except ImportError as exc:
        raise TrainingError(
            "Faltan dependencias de deep learning. Reconstruye el backend con torch y pillow instalados."
        ) from exc

    artifact_path.mkdir(parents=True, exist_ok=True)
    materialized_root = artifact_path / "dataset"
    if materialized_root.exists():
        shutil.rmtree(materialized_root)
    materialized_root.mkdir(parents=True, exist_ok=True)

    samples = _collect_samples(events, data_dir)
    if not samples:
        raise TrainingError("El dataset no tiene evidencias con imagen_path accesible para entrenar.")

    labels = sorted({sample["label"] for sample in samples})
    if len(labels) < 2:
        raise TrainingError("Se necesitan al menos dos categorias con evidencia para entrenar un clasificador.")

    counts = {label: sum(1 for sample in samples if sample["label"] == label) for label in labels}
    low_classes = [label for label, count in counts.items() if count < min_samples_per_class]
    if low_classes:
        raise TrainingError(f"Categorias con evidencia insuficiente: {', '.join(low_classes)}")

    train_samples, val_samples = _split_samples(samples)
    label_to_index = {label: index for index, label in enumerate(labels)}
    labels_path = artifact_path / "labels.json"
    labels_path.write_text(json.dumps({"labels": labels, "label_to_index": label_to_index}, indent=2), encoding="utf-8")

    _materialize_samples(train_samples, materialized_root / "train", Image, ImageOps, image_size)
    _materialize_samples(val_samples, materialized_root / "val", Image, ImageOps, image_size)

    train_dataset = ImageEventDataset(train_samples, label_to_index, Image, ImageOps, image_size)
    val_dataset = ImageEventDataset(val_samples, label_to_index, Image, ImageOps, image_size)
    generator = torch.Generator().manual_seed(42)
    train_loader = DataLoader(train_dataset, batch_size=min(16, max(1, len(train_dataset))), shuffle=True, generator=generator)
    val_loader = DataLoader(val_dataset, batch_size=min(16, max(1, len(val_dataset))), shuffle=False)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_small_cnn(num_classes=len(labels)).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    criterion = nn.CrossEntropyLoss()

    history: list[dict[str, float | int]] = []
    best_state = None
    best_val_accuracy = -1.0
    for epoch in range(1, epochs + 1):
        train_loss, train_accuracy = _run_epoch(model, train_loader, criterion, device, optimizer=optimizer)
        val_loss, val_accuracy = _run_epoch(model, val_loader, criterion, device)
        history.append(
            {
                "epoch": epoch,
                "train_loss": train_loss,
                "train_accuracy": train_accuracy,
                "val_loss": val_loss,
                "val_accuracy": val_accuracy,
            }
        )
        if val_accuracy >= best_val_accuracy:
            best_val_accuracy = val_accuracy
            best_state = {key: value.detach().cpu() for key, value in model.state_dict().items()}

    if best_state is not None:
        model.load_state_dict(best_state)

    model_path = artifact_path / "model.pt"
    cpu_state = {key: value.detach().cpu() for key, value in model.state_dict().items()}
    torch.save(
        {
            "version": version,
            "purpose": purpose,
            "image_size": image_size,
            "labels": labels,
            "state_dict": cpu_state,
            "architecture": "SmallCnn",
        },
        model_path,
    )

    dataset_summary = {
        "events": len(samples),
        "categories": counts,
        "train_samples": len(train_samples),
        "val_samples": len(val_samples),
        "image_size": image_size,
        "source": "event_images",
    }
    metrics = {
        "status": "trained",
        "accuracy": best_val_accuracy,
        "best_val_accuracy": best_val_accuracy,
        "epochs": epochs,
        "device": str(device),
        "history": history,
    }
    metrics_path = artifact_path / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    manifest_path = artifact_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": version,
                "purpose": purpose,
                "notes": notes,
                "model_path": str(model_path),
                "labels_path": str(labels_path),
                "metrics_path": str(metrics_path),
                "dataset": dataset_summary,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return TrainingResult(
        artifact_path=artifact_path,
        model_path=model_path,
        labels_path=labels_path,
        metrics_path=metrics_path,
        manifest_path=manifest_path,
        dataset_summary=dataset_summary,
        metrics=metrics,
    )


class ImageEventDataset:
    def __init__(self, samples: list[dict[str, Any]], label_to_index: dict[str, int], image_cls: Any, image_ops: Any, image_size: int) -> None:
        self.samples = samples
        self.label_to_index = label_to_index
        self.image_cls = image_cls
        self.image_ops = image_ops
        self.image_size = image_size

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int):
        import torch

        sample = self.samples[index]
        image = _load_image(sample, self.image_cls, self.image_ops, self.image_size)
        channels = list(image.getdata())
        tensor = torch.tensor(channels, dtype=torch.float32).view(self.image_size, self.image_size, 3)
        tensor = tensor.permute(2, 0, 1) / 255.0
        return tensor, torch.tensor(self.label_to_index[sample["label"]], dtype=torch.long)


def build_small_cnn(num_classes: int):
    from torch import nn

    return nn.Sequential(
        nn.Conv2d(3, 16, kernel_size=3, padding=1),
        nn.BatchNorm2d(16),
        nn.ReLU(),
        nn.MaxPool2d(2),
        nn.Conv2d(16, 32, kernel_size=3, padding=1),
        nn.BatchNorm2d(32),
        nn.ReLU(),
        nn.MaxPool2d(2),
        nn.Conv2d(32, 64, kernel_size=3, padding=1),
        nn.BatchNorm2d(64),
        nn.ReLU(),
        nn.AdaptiveAvgPool2d((1, 1)),
        nn.Flatten(),
        nn.Dropout(0.2),
        nn.Linear(64, num_classes),
    )


def _collect_samples(events: list[TrainingEvent], data_dir: Path) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for event in events:
        path = _resolve_media_path(event.image_path, data_dir)
        if path is None:
            continue
        metadata = _parse_metadata(event.metadata_json)
        samples.append({"event_id": event.id, "label": event.label, "path": path, "metadata": metadata})
    return samples


def _resolve_media_path(raw_path: str | None, data_dir: Path) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.exists():
        return path
    normalized = str(raw_path).replace("\\", "/")
    for marker in ("/events/", "/snapshots/"):
        index = normalized.find(marker)
        if index >= 0:
            candidate = data_dir / normalized[index + 1 :]
            if candidate.exists():
                return candidate
    candidate = data_dir / normalized.lstrip("/")
    if candidate.exists():
        return candidate
    return None


def _parse_metadata(raw_metadata: str | None) -> dict[str, Any]:
    if not raw_metadata:
        return {}
    try:
        parsed = json.loads(raw_metadata)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _split_samples(samples: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rng = random.Random(42)
    train: list[dict[str, Any]] = []
    val: list[dict[str, Any]] = []
    for label in sorted({sample["label"] for sample in samples}):
        class_samples = [sample for sample in samples if sample["label"] == label]
        rng.shuffle(class_samples)
        if len(class_samples) == 1:
            train.extend(class_samples)
            val.extend(class_samples)
            continue
        val_count = max(1, int(round(len(class_samples) * 0.2)))
        val.extend(class_samples[:val_count])
        train.extend(class_samples[val_count:])
    rng.shuffle(train)
    rng.shuffle(val)
    return train, val or train


def _materialize_samples(samples: list[dict[str, Any]], root: Path, image_cls: Any, image_ops: Any, image_size: int) -> None:
    for sample in samples:
        target_dir = root / _safe_label(sample["label"])
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"event_{sample['event_id']}.jpg"
        image = _load_image(sample, image_cls, image_ops, image_size)
        image.save(target, format="JPEG", quality=92)


def _load_image(sample: dict[str, Any], image_cls: Any, image_ops: Any, image_size: int):
    with image_cls.open(sample["path"]) as image:
        image = image.convert("RGB")
        image = _crop_roi(image, sample.get("metadata") or {})
        return image_ops.fit(image, (image_size, image_size), method=image_cls.Resampling.BILINEAR)


def _crop_roi(image: Any, metadata: dict[str, Any]):
    if metadata.get("analysis_region") != "screen_roi":
        return image
    try:
        x = float(metadata["roi_x"])
        y = float(metadata["roi_y"])
        width = float(metadata["roi_width"])
        height = float(metadata["roi_height"])
    except (KeyError, TypeError, ValueError):
        return image
    image_width, image_height = image.size
    left = max(0, min(image_width - 1, int(x * image_width)))
    upper = max(0, min(image_height - 1, int(y * image_height)))
    right = max(left + 1, min(image_width, int((x + width) * image_width)))
    lower = max(upper + 1, min(image_height, int((y + height) * image_height)))
    return image.crop((left, upper, right, lower))


def _run_epoch(model: Any, loader: Any, criterion: Any, device: Any, optimizer: Any | None = None) -> tuple[float, float]:
    import torch

    training = optimizer is not None
    model.train(training)
    total_loss = 0.0
    total = 0
    correct = 0
    with torch.set_grad_enabled(training):
        for images, targets in loader:
            images = images.to(device)
            targets = targets.to(device)
            outputs = model(images)
            loss = criterion(outputs, targets)
            if training:
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
            total_loss += float(loss.item()) * int(targets.size(0))
            predictions = outputs.argmax(dim=1)
            correct += int((predictions == targets).sum().item())
            total += int(targets.size(0))
    return (total_loss / max(total, 1), correct / max(total, 1))


def _safe_label(label: str) -> str:
    return "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in label).strip("_") or "label"
