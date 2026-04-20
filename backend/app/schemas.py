from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.models import Role


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class UserCreate(LoginRequest):
    role: Role = Role.viewer
    active: bool = True
    must_change_password: bool = True


class UserRead(BaseModel):
    id: int
    email: EmailStr
    role: Role
    active: bool
    must_change_password: bool
    last_login_at: datetime | None = None
    session_count: int = 0
    password_changed_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    role: Role | None = None
    active: bool | None = None
    must_change_password: bool | None = None


class UserPasswordReset(BaseModel):
    password: str = Field(min_length=6)
    must_change_password: bool = True


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=6)
    new_password: str = Field(min_length=6)


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1)
    enabled: bool = True
    capture_fps: int = Field(default=5, ge=1, le=60)
    rotation_degrees: Literal[0, 90, 180, 270] = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False
    digital_brightness: int = Field(default=0, ge=-100, le=100)
    digital_contrast: float = Field(default=1.0, ge=0.1, le=3.0)
    digital_gamma: float = Field(default=1.0, ge=0.1, le=3.0)
    roi_x: float | None = Field(default=None, ge=0, le=1)
    roi_y: float | None = Field(default=None, ge=0, le=1)
    roi_width: float | None = Field(default=None, gt=0, le=1)
    roi_height: float | None = Field(default=None, gt=0, le=1)


class CameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    source: str | None = Field(default=None, min_length=1)
    enabled: bool | None = None
    capture_fps: int | None = Field(default=None, ge=1, le=60)
    rotation_degrees: Literal[0, 90, 180, 270] | None = None
    flip_horizontal: bool | None = None
    flip_vertical: bool | None = None
    digital_brightness: int | None = Field(default=None, ge=-100, le=100)
    digital_contrast: float | None = Field(default=None, ge=0.1, le=3.0)
    digital_gamma: float | None = Field(default=None, ge=0.1, le=3.0)
    roi_x: float | None = Field(default=None, ge=0, le=1)
    roi_y: float | None = Field(default=None, ge=0, le=1)
    roi_width: float | None = Field(default=None, gt=0, le=1)
    roi_height: float | None = Field(default=None, gt=0, le=1)


class CameraRead(CameraCreate):
    id: int
    created_at: datetime
    locked_by_test_id: int | None = None
    locked_by_test_name: str | None = None

    model_config = {"from_attributes": True}


class EventCreate(BaseModel):
    camera_id: int
    type: str = Field(min_length=1, max_length=120)
    confidence: float = Field(default=1.0, ge=0, le=1)
    image_path: str | None = None
    clip_path: str | None = None
    ad_fingerprint: str | None = None
    metadata_json: str | None = None


class EventLabelRead(BaseModel):
    id: int
    label: str
    notes: str | None = None
    user_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class EventRead(EventCreate):
    id: int
    timestamp: datetime
    labels: list[EventLabelRead] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ManualEventCreate(BaseModel):
    camera_id: int
    type: str = Field(min_length=1, max_length=120)
    start_time: datetime
    end_time: datetime
    recording_paths: list[str] = Field(default_factory=list)
    notes: str | None = None


class RecordingChunk(BaseModel):
    camera_id: int
    path: str
    url: str
    start_time: datetime
    end_time: datetime
    duration_seconds: int


class CameraRecordingStatus(BaseModel):
    camera_id: int
    chunk_count: int
    latest_path: str | None = None
    latest_url: str | None = None
    latest_start_time: datetime | None = None
    recording: bool = False


class TestSessionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    camera_ids: list[int] = Field(min_length=1)
    chunk_seconds: int = Field(default=60, ge=5, le=3600)
    duration_minutes: int = Field(default=240, ge=1, le=10080)


class TestSessionRead(TestSessionCreate):
    id: int
    started_at: datetime
    ends_at: datetime
    status: str
    created_by_id: int | None = None

    model_config = {"from_attributes": True}


class LabelCreate(BaseModel):
    event_id: int
    label: str = Field(min_length=1, max_length=120)
    notes: str | None = None


class BulkLabelCreate(BaseModel):
    event_ids: list[int] = Field(min_length=1)
    label: str = Field(min_length=1, max_length=120)
    notes: str | None = None


class LabelRead(LabelCreate):
    id: int
    user_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ModelCreate(BaseModel):
    version: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, max_length=160)
    purpose: str = Field(default="event_classifier", min_length=1, max_length=120, pattern=r"^[a-z0-9_]+$")
    path: str = Field(min_length=1)
    accuracy: float | None = Field(default=None, ge=0, le=1)
    epochs: int | None = Field(default=None, ge=1, le=100000)
    status: str = Field(default="registered", min_length=1, max_length=40)
    active: bool = False
    dataset_summary_json: str | None = None
    metrics_json: str | None = None


class ModelRead(ModelCreate):
    id: int
    version: str
    created_by_id: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TrainRequest(BaseModel):
    purpose: str = Field(default="event_classifier", min_length=1, max_length=120, pattern=r"^[a-z0-9_]+$")
    epochs: int = Field(default=10, ge=1, le=100000)
    dataset_id: int | None = None
    notes: str | None = None
    activate: bool = False


class DatasetStats(BaseModel):
    events: int
    labels: int
    recordings: int
    categories: dict[str, int]


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    event_ids: list[int] = Field(min_length=1)
    parent_dataset_id: int | None = None


class DatasetRead(DatasetCreate):
    id: int
    version: str
    summary_json: str | None = None
    created_by_id: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class EventCategoryCreate(BaseModel):
    key: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    critical: bool = False
    active: bool = True


class EventCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    critical: bool | None = None
    active: bool | None = None


class EventCategoryRead(EventCategoryCreate):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}
