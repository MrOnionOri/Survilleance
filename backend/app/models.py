from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Role(StrEnum):
    admin = "admin"
    supervisor = "supervisor"
    analyst = "analyst"
    viewer = "viewer"


class EventType(StrEnum):
    normal = "normal"
    freeze = "freeze"
    black_screen = "black_screen"
    buffering = "buffering"
    ad = "ad"
    repeated_ad = "repeated_ad"
    scene_change = "scene_change"


DEFAULT_EVENT_CATEGORIES = [
    ("normal", "Normal", False),
    ("freeze", "Freeze", True),
    ("black_screen", "Pantalla negra", True),
    ("buffering", "Buffering", True),
    ("ad", "Anuncio", False),
    ("repeated_ad", "Anuncio repetido", True),
    ("scene_change", "Cambio de escena", False),
]


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.viewer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    labels: Mapped[list["Label"]] = relationship(back_populates="user")


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    source: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=True)
    roi_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    roi_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    roi_width: Mapped[float | None] = mapped_column(Float, nullable=True)
    roi_height: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    events: Mapped[list["Event"]] = relationship(back_populates="camera")


class TestSession(Base):
    __tablename__ = "test_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    camera_ids_json: Mapped[str] = mapped_column(Text)
    chunk_seconds: Mapped[int] = mapped_column(default=60)
    duration_minutes: Mapped[int] = mapped_column(default=240)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(40), default="running", index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"))
    type: Mapped[str] = mapped_column(String(120), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    clip_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    ad_fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    camera: Mapped[Camera] = relationship(back_populates="events")
    labels: Mapped[list["Label"]] = relationship(back_populates="event")


class Label(Base):
    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    label: Mapped[str] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    event: Mapped[Event] = relationship(back_populates="labels")
    user: Mapped[User] = relationship(back_populates="labels")


class AIModel(Base):
    __tablename__ = "models"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    version: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    purpose: Mapped[str] = mapped_column(String(120), default="event_classifier", index=True)
    path: Mapped[str] = mapped_column(Text)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    epochs: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="registered", index=True)
    active: Mapped[bool] = mapped_column(default=False, index=True)
    dataset_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventCategory(Base):
    __tablename__ = "event_categories"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    critical: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    version: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_ids_json: Mapped[str] = mapped_column(Text)
    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_dataset_id: Mapped[int | None] = mapped_column(ForeignKey("dataset_versions.id"), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
