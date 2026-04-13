from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models import EventType, Role


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class UserCreate(LoginRequest):
    role: Role = Role.viewer


class UserRead(BaseModel):
    id: int
    email: EmailStr
    role: Role

    model_config = {"from_attributes": True}


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1)
    enabled: bool = True


class CameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    source: str | None = Field(default=None, min_length=1)
    enabled: bool | None = None


class CameraRead(CameraCreate):
    id: int
    created_at: datetime
    locked_by_test_id: int | None = None
    locked_by_test_name: str | None = None

    model_config = {"from_attributes": True}


class EventCreate(BaseModel):
    camera_id: int
    type: EventType
    confidence: float = Field(default=1.0, ge=0, le=1)
    image_path: str | None = None
    clip_path: str | None = None
    ad_fingerprint: str | None = None
    metadata_json: str | None = None


class EventRead(EventCreate):
    id: int
    timestamp: datetime

    model_config = {"from_attributes": True}


class ManualEventCreate(BaseModel):
    camera_id: int
    type: EventType
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
    label: EventType
    notes: str | None = None


class LabelRead(LabelCreate):
    id: int
    user_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ModelCreate(BaseModel):
    version: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1)
    accuracy: float | None = Field(default=None, ge=0, le=1)


class ModelRead(ModelCreate):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}
