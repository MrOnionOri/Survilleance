import asyncio
import logging
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, SessionLocal, engine, get_db
from app.models import AIModel, Camera, DatasetVersion, Event, EventCategory, Label, Role, TestSession, User
from app.schemas import (
    CameraCreate,
    CameraRecordingStatus,
    CameraRead,
    CameraUpdate,
    DatasetCreate,
    DatasetRead,
    DatasetStats,
    EventCreate,
    EventCategoryCreate,
    EventCategoryRead,
    EventCategoryUpdate,
    EventRead,
    BulkLabelCreate,
    LabelCreate,
    LabelRead,
    LoginRequest,
    ManualEventCreate,
    ModelCreate,
    ModelRead,
    PasswordChangeRequest,
    RecordingChunk,
    TrainRequest,
    Token,
    TestSessionCreate,
    TestSessionRead,
    UserCreate,
    UserPasswordReset,
    UserRead,
    UserUpdate,
)
from app.security import (
    CanConfigure,
    CanLabel,
    CanTrain,
    CanView,
    create_access_token,
    get_current_user,
    get_user_from_token,
    hash_password,
    verify_password,
)
from app.seed import seed_admin, seed_event_categories
from app.training import TrainingError, TrainingEvent, train_image_classifier


settings = get_settings()
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
logger = logging.getLogger("streamwatch")
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
app = FastAPI(title=settings.app_name, version="0.1.0")
app.state.limiter = limiter


async def rate_limit_handler(_: Request, __: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
settings.streamwatch_data_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.streamwatch_data_dir), name="media")


class StreamHub:
    def __init__(self) -> None:
        self.viewers: dict[int, set[WebSocket]] = {}
        self.init_segments: dict[int, bytes] = {}
        self.producer_buffers: dict[int, bytearray] = {}
        self.pending_init: dict[int, bytearray] = {}
        self.pending_media: dict[int, bytearray] = {}
        self.jpeg_frames: dict[int, bytes] = {}
        self.jpeg_versions: dict[int, int] = {}
        self.jpeg_conditions: dict[int, asyncio.Condition] = {}

    async def add_viewer(self, camera_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.viewers.setdefault(camera_id, set()).add(websocket)
        init_segment = self.init_segments.get(camera_id)
        if init_segment:
            try:
                await websocket.send_bytes(init_segment)
            except Exception:
                self.remove_viewer(camera_id, websocket)

    def remove_viewer(self, camera_id: int, websocket: WebSocket) -> None:
        self.viewers.get(camera_id, set()).discard(websocket)

    async def broadcast(self, camera_id: int, frame: bytes) -> None:
        for chunk in self.video_chunks(camera_id, frame):
            await self._broadcast(camera_id, chunk)

    async def update_jpeg(self, camera_id: int, frame: bytes) -> None:
        self.jpeg_frames[camera_id] = frame
        self.jpeg_versions[camera_id] = self.jpeg_versions.get(camera_id, 0) + 1
        condition = self.jpeg_conditions.setdefault(camera_id, asyncio.Condition())
        async with condition:
            condition.notify_all()

    async def mjpeg_frames(self, camera_id: int):
        boundary = b"--streamwatch\r\nContent-Type: image/jpeg\r\nCache-Control: no-cache\r\n\r\n"
        version = -1
        condition = self.jpeg_conditions.setdefault(camera_id, asyncio.Condition())
        while True:
            current_version = self.jpeg_versions.get(camera_id, 0)
            if current_version == version:
                async with condition:
                    try:
                        await asyncio.wait_for(condition.wait(), timeout=10)
                    except asyncio.TimeoutError:
                        pass
                current_version = self.jpeg_versions.get(camera_id, 0)
            frame = self.jpeg_frames.get(camera_id)
            if frame and current_version != version:
                version = current_version
                yield boundary + frame + b"\r\n"

    def reset_producer(self, camera_id: int) -> None:
        self.init_segments.pop(camera_id, None)
        self.producer_buffers.pop(camera_id, None)
        self.pending_init.pop(camera_id, None)
        self.pending_media.pop(camera_id, None)

    def video_chunks(self, camera_id: int, chunk: bytes) -> list[bytes]:
        buffer = self.producer_buffers.setdefault(camera_id, bytearray())
        buffer.extend(chunk)
        chunks: list[bytes] = []

        while True:
            box = self._pop_complete_mp4_box(buffer)
            if box is None:
                break
            box_type = box[4:8]
            if box_type in {b"ftyp", b"moov"} and camera_id not in self.init_segments:
                pending_init = self.pending_init.setdefault(camera_id, bytearray())
                pending_init.extend(box)
                if box_type == b"moov":
                    init_segment = bytes(pending_init)
                    self.init_segments[camera_id] = init_segment
                    self.pending_init.pop(camera_id, None)
                    chunks.append(init_segment)
                continue

            if box_type == b"moof":
                pending_media = self.pending_media.setdefault(camera_id, bytearray())
                if pending_media:
                    chunks.append(bytes(pending_media))
                    pending_media.clear()
                pending_media.extend(box)
                continue

            if box_type == b"mdat":
                pending_media = self.pending_media.setdefault(camera_id, bytearray())
                pending_media.extend(box)
                chunks.append(bytes(pending_media))
                pending_media.clear()
                continue

            pending_media = self.pending_media.setdefault(camera_id, bytearray())
            if pending_media:
                pending_media.extend(box)

        return chunks

    def _pop_complete_mp4_box(self, buffer: bytearray) -> bytes | None:
        if len(buffer) < 8:
            return None

        size = int.from_bytes(buffer[:4], "big")
        header_size = 8
        if size == 1:
            if len(buffer) < 16:
                return None
            size = int.from_bytes(buffer[8:16], "big")
            header_size = 16
        elif size == 0:
            size = len(buffer)

        if size < header_size or len(buffer) < size:
            return None

        box = bytes(buffer[:size])
        del buffer[:size]
        return box

    async def _broadcast(self, camera_id: int, frame: bytes) -> None:
        dead: list[WebSocket] = []
        for viewer in self.viewers.get(camera_id, set()).copy():
            try:
                await viewer.send_bytes(frame)
            except Exception:
                dead.append(viewer)
        for viewer in dead:
            self.remove_viewer(camera_id, viewer)


stream_hub = StreamHub()
field_test_camera_ids: set[int] = set()


@app.middleware("http")
async def access_log(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info(
        "ACCESS method=%s path=%s status=%s duration_ms=%s",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    run_lightweight_migrations()
    with SessionLocal() as db:
        seed_admin(db)
        seed_event_categories(db)


def run_lightweight_migrations() -> None:
    with engine.begin() as connection:
        if settings.database_url.startswith("postgres"):
            connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE"))
            connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN DEFAULT FALSE"))
            connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP WITH TIME ZONE"))
            connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS session_count INTEGER DEFAULT 0"))
            connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMP WITH TIME ZONE"))
            connection.execute(text("UPDATE users SET active = TRUE WHERE active IS NULL"))
            connection.execute(text("UPDATE users SET must_change_password = FALSE WHERE must_change_password IS NULL"))
            connection.execute(text("UPDATE users SET session_count = 0 WHERE session_count IS NULL"))
            connection.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS capture_fps INTEGER DEFAULT 5"))
            connection.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS rotation_degrees INTEGER DEFAULT 0"))
            connection.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS flip_horizontal BOOLEAN DEFAULT FALSE"))
            connection.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS flip_vertical BOOLEAN DEFAULT FALSE"))
            connection.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS digital_brightness INTEGER DEFAULT 0"))
            connection.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS digital_contrast DOUBLE PRECISION DEFAULT 1.0"))
            connection.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS digital_gamma DOUBLE PRECISION DEFAULT 1.0"))
            connection.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS roi_x DOUBLE PRECISION"))
            connection.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS roi_y DOUBLE PRECISION"))
            connection.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS roi_width DOUBLE PRECISION"))
            connection.execute(text("ALTER TABLE cameras ADD COLUMN IF NOT EXISTS roi_height DOUBLE PRECISION"))
            connection.execute(text("ALTER TABLE events ALTER COLUMN type TYPE VARCHAR(120) USING type::text"))
            connection.execute(text("ALTER TABLE labels ALTER COLUMN label TYPE VARCHAR(120) USING label::text"))
            connection.execute(text("ALTER TABLE event_categories ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE"))
            connection.execute(text("UPDATE event_categories SET active = TRUE WHERE active IS NULL"))
            connection.execute(text("ALTER TABLE models ADD COLUMN IF NOT EXISTS name VARCHAR(160)"))
            connection.execute(text("ALTER TABLE models ADD COLUMN IF NOT EXISTS purpose VARCHAR(120) DEFAULT 'event_classifier'"))
            connection.execute(text("ALTER TABLE models ADD COLUMN IF NOT EXISTS epochs INTEGER"))
            connection.execute(text("ALTER TABLE models ADD COLUMN IF NOT EXISTS status VARCHAR(40) DEFAULT 'registered'"))
            connection.execute(text("ALTER TABLE models ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT FALSE"))
            connection.execute(text("ALTER TABLE models ADD COLUMN IF NOT EXISTS dataset_summary_json TEXT"))
            connection.execute(text("ALTER TABLE models ADD COLUMN IF NOT EXISTS metrics_json TEXT"))
            connection.execute(text("ALTER TABLE models ADD COLUMN IF NOT EXISTS created_by_id INTEGER"))
            connection.execute(text("ALTER TABLE dataset_versions ADD COLUMN IF NOT EXISTS parent_dataset_id INTEGER"))
        elif settings.database_url.startswith("sqlite"):
            user_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(users)"))}
            sqlite_user_columns = {
                "active": "BOOLEAN DEFAULT 1",
                "must_change_password": "BOOLEAN DEFAULT 0",
                "last_login_at": "DATETIME",
                "session_count": "INTEGER DEFAULT 0",
                "password_changed_at": "DATETIME",
            }
            for column, column_type in sqlite_user_columns.items():
                if column not in user_columns:
                    connection.execute(text(f"ALTER TABLE users ADD COLUMN {column} {column_type}"))
            connection.execute(text("UPDATE users SET active = 1 WHERE active IS NULL"))
            connection.execute(text("UPDATE users SET must_change_password = 0 WHERE must_change_password IS NULL"))
            connection.execute(text("UPDATE users SET session_count = 0 WHERE session_count IS NULL"))
            columns = {row[1] for row in connection.execute(text("PRAGMA table_info(cameras)"))}
            sqlite_camera_columns = {
                "capture_fps": "INTEGER DEFAULT 5",
                "rotation_degrees": "INTEGER DEFAULT 0",
                "flip_horizontal": "BOOLEAN DEFAULT 0",
                "flip_vertical": "BOOLEAN DEFAULT 0",
                "digital_brightness": "INTEGER DEFAULT 0",
                "digital_contrast": "FLOAT DEFAULT 1.0",
                "digital_gamma": "FLOAT DEFAULT 1.0",
            }
            for column, column_type in sqlite_camera_columns.items():
                if column not in columns:
                    connection.execute(text(f"ALTER TABLE cameras ADD COLUMN {column} {column_type}"))
            for column in ["roi_x", "roi_y", "roi_width", "roi_height"]:
                if column not in columns:
                    connection.execute(text(f"ALTER TABLE cameras ADD COLUMN {column} FLOAT"))
            model_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(models)"))}
            sqlite_model_columns = {
                "name": "VARCHAR(160)",
                "purpose": "VARCHAR(120) DEFAULT 'event_classifier'",
                "epochs": "INTEGER",
                "status": "VARCHAR(40) DEFAULT 'registered'",
                "active": "BOOLEAN DEFAULT 0",
                "dataset_summary_json": "TEXT",
                "metrics_json": "TEXT",
                "created_by_id": "INTEGER",
            }
            for column, column_type in sqlite_model_columns.items():
                if column not in model_columns:
                    connection.execute(text(f"ALTER TABLE models ADD COLUMN {column} {column_type}"))
            dataset_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(dataset_versions)"))}
            if "parent_dataset_id" not in dataset_columns:
                connection.execute(text("ALTER TABLE dataset_versions ADD COLUMN parent_dataset_id INTEGER"))
            category_columns = {row[1] for row in connection.execute(text("PRAGMA table_info(event_categories)"))}
            if "active" not in category_columns:
                connection.execute(text("ALTER TABLE event_categories ADD COLUMN active BOOLEAN DEFAULT 1"))
                connection.execute(text("UPDATE event_categories SET active = 1 WHERE active IS NULL"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.get("/field-tests/cameras")
def list_field_test_cameras(_: CanLabel) -> dict[str, list[int]]:
    return {"camera_ids": sorted(field_test_camera_ids)}


@app.post("/field-tests/cameras/{camera_id}")
def start_field_test_camera(camera_id: int, db: Annotated[Session, Depends(get_db)], _: CanLabel) -> dict[str, str | int]:
    camera = db.get(Camera, camera_id)
    if not camera or not camera.enabled:
        raise HTTPException(status_code=404, detail="Camera not found or disabled")
    field_test_camera_ids.add(camera_id)
    return {"status": "active", "camera_id": camera_id}


@app.delete("/field-tests/cameras/{camera_id}")
def stop_field_test_camera(camera_id: int, _: CanLabel) -> dict[str, str | int]:
    field_test_camera_ids.discard(camera_id)
    return {"status": "stopped", "camera_id": camera_id}


@app.get("/cameras/{camera_id}/mjpeg")
async def camera_mjpeg(camera_id: int, token: str) -> StreamingResponse:
    with SessionLocal() as db:
        user = get_user_from_token(token, db)
        camera = db.get(Camera, camera_id)
    if not user or not user.active or user.must_change_password or not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    return StreamingResponse(
        stream_hub.mjpeg_frames(camera_id),
        media_type="multipart/x-mixed-replace; boundary=streamwatch",
        headers={"Cache-Control": "no-store"},
    )


@app.websocket("/ws/cameras/{camera_id}/stream")
async def camera_stream(websocket: WebSocket, camera_id: int, token: str, mode: str = "viewer") -> None:
    with SessionLocal() as db:
        user = get_user_from_token(token, db)
        camera = db.get(Camera, camera_id)
    if not user or not user.active or user.must_change_password or not camera:
        await websocket.close(code=1008)
        return

    if mode == "producer":
        if user.role.value not in {"admin", "supervisor"}:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        stream_hub.reset_producer(camera_id)
        try:
            while True:
                frame = await websocket.receive_bytes()
                await stream_hub.broadcast(camera_id, frame)
        except WebSocketDisconnect:
            return

    if mode == "producer_jpeg":
        if user.role.value not in {"admin", "supervisor"}:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            while True:
                frame = await websocket.receive_bytes()
                await stream_hub.update_jpeg(camera_id, frame)
        except WebSocketDisconnect:
            return

    await stream_hub.add_viewer(camera_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        stream_hub.remove_viewer(camera_id, websocket)


@app.post("/auth/login", response_model=Token)
def login(payload: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> Token:
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not user.active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")
    user.last_login_at = datetime.now(UTC)
    user.session_count = (user.session_count or 0) + 1
    db.commit()
    return Token(access_token=create_access_token(user.email))


@app.post("/auth/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Annotated[Session, Depends(get_db)], _: CanConfigure) -> User:
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        active=payload.active,
        must_change_password=payload.must_change_password,
        password_changed_at=datetime.now(UTC),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.get("/auth/me", response_model=UserRead)
def me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user


@app.post("/auth/change-password", response_model=UserRead)
def change_password(
    payload: PasswordChangeRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
    current_user.password_hash = hash_password(payload.new_password)
    current_user.must_change_password = False
    current_user.password_changed_at = datetime.now(UTC)
    db.commit()
    db.refresh(current_user)
    return current_user


@app.get("/users", response_model=list[UserRead])
def list_users(db: Annotated[Session, Depends(get_db)], _: CanConfigure) -> list[User]:
    return list(db.scalars(select(User).order_by(User.active.desc(), User.email)))


@app.patch("/users/{user_id}", response_model=UserRead)
def update_user(user_id: int, payload: UserUpdate, db: Annotated[Session, Depends(get_db)], current_user: CanConfigure) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    changes = payload.model_dump(exclude_unset=True)
    if user.id == current_user.id and changes.get("active") is False:
        raise HTTPException(status_code=422, detail="You cannot deactivate your own user")
    if user.id == current_user.id and "role" in changes and changes["role"] != Role.admin:
        raise HTTPException(status_code=422, detail="You cannot remove your own admin role")
    for field, value in changes.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


@app.post("/users/{user_id}/password", response_model=UserRead)
def reset_user_password(
    user_id: int,
    payload: UserPasswordReset,
    db: Annotated[Session, Depends(get_db)],
    _: CanConfigure,
) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.password_hash = hash_password(payload.password)
    user.must_change_password = payload.must_change_password
    user.password_changed_at = datetime.now(UTC)
    db.commit()
    db.refresh(user)
    return user


@app.get("/cameras", response_model=list[CameraRead])
def list_cameras(
    db: Annotated[Session, Depends(get_db)],
    _: CanView,
    include_disabled: bool = Query(default=False),
) -> list[CameraRead]:
    expire_finished_tests(db)
    query = select(Camera).order_by(Camera.id)
    if not include_disabled:
        query = query.where(Camera.enabled.is_(True))
    cameras = list(db.scalars(query))
    running_tests = list(db.scalars(select(TestSession).where(TestSession.status == "running")))
    locks: dict[int, tuple[int, str]] = {}
    for test in running_tests:
        for camera_id in json.loads(test.camera_ids_json):
            locks[camera_id] = (test.id, test.name)
    return [
        CameraRead(
            id=camera.id,
            name=camera.name,
            source=camera.source,
            enabled=camera.enabled,
            capture_fps=camera.capture_fps or 5,
            rotation_degrees=camera.rotation_degrees or 0,
            flip_horizontal=bool(camera.flip_horizontal),
            flip_vertical=bool(camera.flip_vertical),
            digital_brightness=camera.digital_brightness or 0,
            digital_contrast=camera.digital_contrast or 1.0,
            digital_gamma=camera.digital_gamma or 1.0,
            roi_x=camera.roi_x,
            roi_y=camera.roi_y,
            roi_width=camera.roi_width,
            roi_height=camera.roi_height,
            created_at=camera.created_at,
            locked_by_test_id=locks.get(camera.id, (None, None))[0],
            locked_by_test_name=locks.get(camera.id, (None, None))[1],
        )
        for camera in cameras
    ]


@app.get("/cameras/{camera_id}", response_model=CameraRead)
def get_camera(camera_id: int, db: Annotated[Session, Depends(get_db)], _: CanView) -> CameraRead:
    expire_finished_tests(db)
    camera = db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    locks: dict[int, tuple[int, str]] = {}
    for test in db.scalars(select(TestSession).where(TestSession.status == "running")).all():
        for locked_camera_id in json.loads(test.camera_ids_json):
            locks[locked_camera_id] = (test.id, test.name)
    return CameraRead(
        id=camera.id,
        name=camera.name,
        source=camera.source,
        enabled=camera.enabled,
        capture_fps=camera.capture_fps or 5,
        rotation_degrees=camera.rotation_degrees or 0,
        flip_horizontal=bool(camera.flip_horizontal),
        flip_vertical=bool(camera.flip_vertical),
        digital_brightness=camera.digital_brightness or 0,
        digital_contrast=camera.digital_contrast or 1.0,
        digital_gamma=camera.digital_gamma or 1.0,
        roi_x=camera.roi_x,
        roi_y=camera.roi_y,
        roi_width=camera.roi_width,
        roi_height=camera.roi_height,
        created_at=camera.created_at,
        locked_by_test_id=locks.get(camera.id, (None, None))[0],
        locked_by_test_name=locks.get(camera.id, (None, None))[1],
    )


@app.post("/cameras", response_model=CameraRead, status_code=status.HTTP_201_CREATED)
def create_camera(payload: CameraCreate, db: Annotated[Session, Depends(get_db)], _: CanConfigure) -> Camera:
    camera = Camera(**payload.model_dump())
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return camera


@app.patch("/cameras/{camera_id}", response_model=CameraRead)
def update_camera(camera_id: int, payload: CameraUpdate, db: Annotated[Session, Depends(get_db)], _: CanConfigure) -> Camera:
    camera = db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    changes = payload.model_dump(exclude_unset=True)
    live_tuning_fields = {
        "roi_x",
        "roi_y",
        "roi_width",
        "roi_height",
        "capture_fps",
        "rotation_degrees",
        "flip_horizontal",
        "flip_vertical",
        "digital_brightness",
        "digital_contrast",
        "digital_gamma",
    }
    if _camera_locked(db, camera_id) and any(field not in live_tuning_fields for field in changes):
        raise HTTPException(status_code=409, detail="Camera is locked by a running test")
    for field, value in changes.items():
        setattr(camera, field, value)
    db.commit()
    db.refresh(camera)
    return camera


@app.delete("/cameras/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(camera_id: int, db: Annotated[Session, Depends(get_db)], _: CanConfigure) -> None:
    camera = db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    if _camera_locked(db, camera_id):
        raise HTTPException(status_code=409, detail="Camera is locked by a running test")
    camera.enabled = False
    db.commit()


def _camera_locked(db: Session, camera_id: int) -> bool:
    expire_finished_tests(db)
    running_tests = db.scalars(select(TestSession).where(TestSession.status == "running")).all()
    return any(camera_id in json.loads(test.camera_ids_json) for test in running_tests)


def expire_finished_tests(db: Session) -> None:
    now = datetime.now(UTC)
    running_tests = db.scalars(select(TestSession).where(TestSession.status == "running")).all()
    expired_tests = [test for test in running_tests if as_utc(test.ends_at) <= now]
    if not expired_tests:
        return
    for test in expired_tests:
        test.status = "finished"
    db.commit()


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _test_to_read(test: TestSession) -> TestSessionRead:
    return TestSessionRead(
        id=test.id,
        name=test.name,
        description=test.description,
        camera_ids=json.loads(test.camera_ids_json),
        chunk_seconds=test.chunk_seconds,
        duration_minutes=test.duration_minutes,
        started_at=test.started_at,
        ends_at=test.ends_at,
        status=test.status,
        created_by_id=test.created_by_id,
    )


@app.get("/tests", response_model=list[TestSessionRead])
def list_tests(db: Annotated[Session, Depends(get_db)], _: CanView) -> list[TestSessionRead]:
    expire_finished_tests(db)
    tests = db.scalars(select(TestSession).order_by(desc(TestSession.started_at))).all()
    return [_test_to_read(test) for test in tests]


@app.post("/tests", response_model=TestSessionRead, status_code=status.HTTP_201_CREATED)
def create_test(payload: TestSessionCreate, db: Annotated[Session, Depends(get_db)], current_user: CanTrain) -> TestSessionRead:
    expire_finished_tests(db)
    cameras_found = db.scalars(select(Camera).where(Camera.id.in_(payload.camera_ids), Camera.enabled.is_(True))).all()
    if len(cameras_found) != len(set(payload.camera_ids)):
        raise HTTPException(status_code=422, detail="One or more cameras are not active")
    locked_camera_ids = [camera_id for camera_id in payload.camera_ids if _camera_locked(db, camera_id)]
    if locked_camera_ids:
        raise HTTPException(status_code=409, detail=f"Cameras already locked by a running test: {locked_camera_ids}")
    started_at = datetime.now(UTC)
    test = TestSession(
        name=payload.name,
        description=payload.description,
        camera_ids_json=json.dumps(payload.camera_ids),
        chunk_seconds=payload.chunk_seconds,
        duration_minutes=payload.duration_minutes,
        started_at=started_at,
        ends_at=started_at + timedelta(minutes=payload.duration_minutes),
        status="running",
        created_by_id=current_user.id,
    )
    db.add(test)
    db.commit()
    db.refresh(test)
    return _test_to_read(test)


@app.patch("/tests/{test_id}/finish", response_model=TestSessionRead)
def finish_test(test_id: int, db: Annotated[Session, Depends(get_db)], _: CanTrain) -> TestSessionRead:
    test = db.get(TestSession, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")
    test.status = "finished"
    test.ends_at = datetime.now(UTC)
    db.commit()
    db.refresh(test)
    return _test_to_read(test)


def ensure_category(db: Session, key: str, require_active: bool = True) -> None:
    query = select(EventCategory).where(EventCategory.key == key)
    if require_active:
        query = query.where(EventCategory.active.is_(True))
    if not db.scalar(query):
        raise HTTPException(status_code=422, detail=f"Unknown event category: {key}")


@app.get("/categories", response_model=list[EventCategoryRead])
def list_categories(
    db: Annotated[Session, Depends(get_db)],
    _: CanView,
    include_disabled: bool = False,
) -> list[EventCategory]:
    query = select(EventCategory).order_by(EventCategory.active.desc(), EventCategory.name)
    if not include_disabled:
        query = query.where(EventCategory.active.is_(True))
    return list(db.scalars(query))


@app.post("/categories", response_model=EventCategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(payload: EventCategoryCreate, db: Annotated[Session, Depends(get_db)], _: CanConfigure) -> EventCategory:
    if db.scalar(select(EventCategory).where(EventCategory.key == payload.key)):
        raise HTTPException(status_code=409, detail="Category already exists")
    category = EventCategory(**payload.model_dump())
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@app.patch("/categories/{category_id}", response_model=EventCategoryRead)
def update_category(
    category_id: int,
    payload: EventCategoryUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: CanConfigure,
) -> EventCategory:
    category = db.get(EventCategory, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(category, field, value)
    db.commit()
    db.refresh(category)
    return category


@app.delete("/categories/{category_id}", response_model=EventCategoryRead)
def disable_category(category_id: int, db: Annotated[Session, Depends(get_db)], _: CanConfigure) -> EventCategory:
    category = db.get(EventCategory, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    category.active = False
    db.commit()
    db.refresh(category)
    return category


@app.get("/events", response_model=list[EventRead])
def list_events(
    db: Annotated[Session, Depends(get_db)],
    _: CanView,
    camera_id: int | None = None,
    event_type: str | None = Query(default=None, alias="type"),
    ids: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[Event]:
    query = select(Event).order_by(desc(Event.timestamp))
    if ids:
        event_ids = [int(value) for value in ids.split(",") if value.strip().isdigit()]
        query = query.where(Event.id.in_(event_ids))
    if camera_id:
        query = query.where(Event.camera_id == camera_id)
    if event_type:
        query = query.where(Event.type == event_type)
    if not ids:
        query = query.limit(limit)
    return list(db.scalars(query))


@app.post("/events", response_model=EventRead, status_code=status.HTTP_201_CREATED)
def create_event(payload: EventCreate, db: Annotated[Session, Depends(get_db)], _: CanTrain) -> Event:
    if not db.get(Camera, payload.camera_id):
        raise HTTPException(status_code=404, detail="Camera not found")
    ensure_category(db, payload.type, require_active=False)
    event = Event(**payload.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@app.post("/events/manual", response_model=EventRead, status_code=status.HTTP_201_CREATED)
def create_manual_event(payload: ManualEventCreate, db: Annotated[Session, Depends(get_db)], current_user: CanLabel) -> Event:
    if payload.end_time <= payload.start_time:
        raise HTTPException(status_code=422, detail="end_time must be greater than start_time")
    if not db.get(Camera, payload.camera_id):
        raise HTTPException(status_code=404, detail="Camera not found")
    ensure_category(db, payload.type)

    metadata = {
        "source": "manual_review",
        "start_time": payload.start_time.isoformat(),
        "end_time": payload.end_time.isoformat(),
        "recording_paths": payload.recording_paths,
        "notes": payload.notes,
    }
    event = Event(
        camera_id=payload.camera_id,
        type=payload.type,
        confidence=1.0,
        clip_path=";".join(payload.recording_paths) if payload.recording_paths else None,
        metadata_json=json.dumps(metadata),
    )
    db.add(event)
    db.flush()
    db.add(Label(event_id=event.id, user_id=current_user.id, label=payload.type, notes=payload.notes))
    db.commit()
    db.refresh(event)
    return event


@app.post("/events/label", response_model=LabelRead, status_code=status.HTTP_201_CREATED)
def label_event(payload: LabelCreate, db: Annotated[Session, Depends(get_db)], current_user: CanLabel) -> Label:
    if not db.get(Event, payload.event_id):
        raise HTTPException(status_code=404, detail="Event not found")
    ensure_category(db, payload.label)
    label = Label(**payload.model_dump(), user_id=current_user.id)
    db.add(label)
    db.commit()
    db.refresh(label)
    return label


@app.post("/events/labels/bulk", response_model=list[LabelRead], status_code=status.HTTP_201_CREATED)
def bulk_label_events(payload: BulkLabelCreate, db: Annotated[Session, Depends(get_db)], current_user: CanLabel) -> list[Label]:
    ensure_category(db, payload.label)
    events = db.scalars(select(Event).where(Event.id.in_(payload.event_ids))).all()
    if len(events) != len(set(payload.event_ids)):
        raise HTTPException(status_code=422, detail="One or more events do not exist")
    labels = [
        Label(event_id=event.id, user_id=current_user.id, label=payload.label, notes=payload.notes)
        for event in events
    ]
    db.add_all(labels)
    db.commit()
    for label in labels:
        db.refresh(label)
    return labels


@app.get("/recordings", response_model=list[RecordingChunk])
def list_recordings(
    db: Annotated[Session, Depends(get_db)],
    _: CanView,
    camera_id: int,
    test_id: int | None = Query(default=None),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    duration_seconds: int = Query(default=60, ge=1, le=3600),
) -> list[RecordingChunk]:
    if not db.get(Camera, camera_id):
        raise HTTPException(status_code=404, detail="Camera not found")

    if test_id:
        test = db.get(TestSession, test_id)
        if not test:
            raise HTTPException(status_code=404, detail="Test not found")
        if camera_id not in json.loads(test.camera_ids_json):
            raise HTTPException(status_code=422, detail="Camera is not part of this test")
        root = settings.streamwatch_data_dir / "recordings" / f"test_{test_id}" / f"cam_{camera_id}"
    else:
        root = settings.streamwatch_data_dir / "recordings" / "unassigned" / f"cam_{camera_id}"
    if not root.exists():
        return []

    parsed_paths = []
    for path in sorted(root.glob("*/*.mp4")):
        chunk_start_time = _chunk_start_time(path)
        if not chunk_start_time:
            continue
        parsed_paths.append((path, chunk_start_time))

    chunks: list[RecordingChunk] = []
    for index, (path, chunk_start_time) in enumerate(parsed_paths):
        next_start_time = parsed_paths[index + 1][1] if index + 1 < len(parsed_paths) else None
        if not next_start_time and datetime.now(UTC) < chunk_start_time + timedelta(seconds=duration_seconds):
            continue
        actual_duration = duration_seconds
        if next_start_time:
            actual_duration = max(1, min(duration_seconds, int((next_start_time - chunk_start_time).total_seconds())))
        chunk_end_time = chunk_start_time + timedelta(seconds=actual_duration)
        if start_time and chunk_end_time <= start_time:
            continue
        if end_time and chunk_start_time >= end_time:
            continue
        rel = path.relative_to(settings.streamwatch_data_dir).as_posix()
        chunks.append(
            RecordingChunk(
                camera_id=camera_id,
                path=str(path),
                url=f"/media/{rel}",
                start_time=chunk_start_time,
                end_time=chunk_start_time + timedelta(seconds=actual_duration),
                duration_seconds=actual_duration,
            )
        )
    return chunks


@app.get("/recordings/status", response_model=list[CameraRecordingStatus])
def recording_status(db: Annotated[Session, Depends(get_db)], _: CanView) -> list[CameraRecordingStatus]:
    cameras = list(db.scalars(select(Camera).order_by(Camera.id)))
    statuses: list[CameraRecordingStatus] = []
    for camera in cameras:
        root = settings.streamwatch_data_dir / "recordings"
        paths = sorted(root.glob(f"test_*/cam_{camera.id}/*/*.mp4")) if root.exists() else []
        latest = paths[-1] if paths else None
        latest_start = _chunk_start_time(latest) if latest else None
        latest_url = None
        if latest:
            rel = latest.relative_to(settings.streamwatch_data_dir).as_posix()
            latest_url = f"/media/{rel}"
        statuses.append(
            CameraRecordingStatus(
                camera_id=camera.id,
                chunk_count=len(paths),
                latest_path=str(latest) if latest else None,
                latest_url=latest_url,
                latest_start_time=latest_start,
                recording=camera.enabled and bool(paths),
            )
        )
    return statuses


def _chunk_start_time(path: Path) -> datetime | None:
    try:
        date_part = path.parent.name
        time_part = path.stem
        parsed = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H-%M-%S")
        return parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


@app.get("/models", response_model=list[ModelRead])
def list_models(
    db: Annotated[Session, Depends(get_db)],
    _: CanLabel,
    purpose: str | None = None,
) -> list[AIModel]:
    query = select(AIModel).order_by(desc(AIModel.created_at))
    if purpose:
        query = query.where(AIModel.purpose == purpose)
    return list(db.scalars(query))


@app.post("/models", response_model=ModelRead, status_code=status.HTTP_201_CREATED)
def register_model(payload: ModelCreate, db: Annotated[Session, Depends(get_db)], current_user: CanTrain) -> AIModel:
    values = payload.model_dump()
    if not values.get("version"):
        values["version"] = make_model_version(values.get("purpose", "event_classifier"), values.get("epochs"))
    if values.get("active"):
        deactivate_models(db, values["purpose"])
    model = AIModel(**values, created_by_id=current_user.id)
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


@app.get("/models/active", response_model=ModelRead)
def active_model(
    db: Annotated[Session, Depends(get_db)],
    _: CanLabel,
    purpose: str = "event_classifier",
) -> AIModel:
    model = db.scalar(select(AIModel).where(AIModel.purpose == purpose, AIModel.active.is_(True)).order_by(desc(AIModel.created_at)))
    if not model:
        raise HTTPException(status_code=404, detail="No active model for this purpose")
    return model


@app.patch("/models/{model_id}/activate", response_model=ModelRead)
def activate_model(model_id: int, db: Annotated[Session, Depends(get_db)], _: CanTrain) -> AIModel:
    model = db.get(AIModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    deactivate_models(db, model.purpose)
    model.active = True
    model.status = "active"
    db.commit()
    db.refresh(model)
    return model


@app.get("/dataset/stats", response_model=DatasetStats)
def dataset_stats(db: Annotated[Session, Depends(get_db)], _: CanLabel) -> DatasetStats:
    categories = {category.key: 0 for category in db.scalars(select(EventCategory)).all()}
    for label in db.scalars(select(Label)).all():
        categories[label.label] = categories.get(label.label, 0) + 1
    recordings_root = settings.streamwatch_data_dir / "recordings"
    recordings = len(list(recordings_root.glob("test_*/cam_*/*/*.mp4"))) if recordings_root.exists() else 0
    return DatasetStats(
        events=len(list(db.scalars(select(Event.id)).all())),
        labels=len(list(db.scalars(select(Label.id)).all())),
        recordings=recordings,
        categories=categories,
    )


@app.get("/datasets", response_model=list[DatasetRead])
def list_datasets(db: Annotated[Session, Depends(get_db)], _: CanLabel) -> list[DatasetRead]:
    datasets = db.scalars(select(DatasetVersion).order_by(desc(DatasetVersion.created_at))).all()
    return [_dataset_to_read(dataset) for dataset in datasets]


@app.post("/datasets", response_model=DatasetRead, status_code=status.HTTP_201_CREATED)
def create_dataset(payload: DatasetCreate, db: Annotated[Session, Depends(get_db)], current_user: CanLabel) -> DatasetRead:
    if payload.parent_dataset_id and not db.get(DatasetVersion, payload.parent_dataset_id):
        raise HTTPException(status_code=404, detail="Parent dataset not found")
    events = db.scalars(select(Event).where(Event.id.in_(payload.event_ids))).all()
    if len(events) != len(set(payload.event_ids)):
        raise HTTPException(status_code=422, detail="One or more events do not exist")
    categories: dict[str, int] = {}
    for event in events:
        label = latest_event_label(event)
        categories[label] = categories.get(label, 0) + 1
    version = make_dataset_version(payload.name)
    dataset = DatasetVersion(
        version=version,
        name=payload.name,
        description=payload.description,
        event_ids_json=json.dumps(sorted(set(payload.event_ids))),
        summary_json=json.dumps({"events": len(events), "categories": categories}),
        parent_dataset_id=payload.parent_dataset_id,
        created_by_id=current_user.id,
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return _dataset_to_read(dataset)


@app.post("/train", response_model=ModelRead, status_code=status.HTTP_201_CREATED)
def train(payload: TrainRequest, db: Annotated[Session, Depends(get_db)], current_user: CanTrain) -> AIModel:
    dataset = db.get(DatasetVersion, payload.dataset_id) if payload.dataset_id else None
    if payload.dataset_id and not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if not dataset:
        raise HTTPException(status_code=422, detail="Select a dataset before training")

    event_ids = json.loads(dataset.event_ids_json)
    events = list(db.scalars(select(Event).where(Event.id.in_(event_ids))).unique())
    if not events:
        raise HTTPException(status_code=422, detail="Dataset has no events")

    version = make_model_version(payload.purpose, payload.epochs)
    artifact_path = settings.streamwatch_data_dir / "models" / payload.purpose / version
    effective_epochs = min(payload.epochs, settings.training_max_epochs)
    training_events = [
        TrainingEvent(
            id=event.id,
            label=latest_event_label(event),
            image_path=event.image_path,
            metadata_json=event.metadata_json,
        )
        for event in events
    ]
    try:
        result = train_image_classifier(
            events=training_events,
            data_dir=settings.streamwatch_data_dir,
            artifact_path=artifact_path,
            version=version,
            purpose=payload.purpose,
            epochs=effective_epochs,
            notes=payload.notes,
            image_size=settings.training_image_size,
        )
    except TrainingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if payload.activate:
        deactivate_models(db, payload.purpose)
    model = AIModel(
        version=version,
        name=f"{payload.purpose} {version}",
        purpose=payload.purpose,
        path=str(result.model_path),
        accuracy=result.metrics.get("accuracy"),
        epochs=effective_epochs,
        status="active" if payload.activate else "trained",
        active=payload.activate,
        dataset_summary_json=json.dumps(result.dataset_summary),
        metrics_json=json.dumps(
            {
                **result.metrics,
                "requested_epochs": payload.epochs,
                "effective_epochs": effective_epochs,
                "dataset_version": dataset.version,
                "artifact_path": str(result.artifact_path),
            }
        ),
        created_by_id=current_user.id,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


def deactivate_models(db: Session, purpose: str) -> None:
    for model in db.scalars(select(AIModel).where(AIModel.purpose == purpose, AIModel.active.is_(True))).all():
        model.active = False
        if model.status == "active":
            model.status = "trained"


def make_model_version(purpose: str, epochs: int | None) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    epoch_part = f"e{epochs or 0:04d}"
    return f"{purpose}_{epoch_part}_{stamp}"


def make_dataset_version(name: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in name).strip("_") or "dataset"
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return f"{cleaned[:40]}_{stamp}"


def _dataset_to_read(dataset: DatasetVersion) -> DatasetRead:
    return DatasetRead(
        id=dataset.id,
        version=dataset.version,
        name=dataset.name,
        description=dataset.description,
        event_ids=json.loads(dataset.event_ids_json),
        parent_dataset_id=dataset.parent_dataset_id,
        summary_json=dataset.summary_json,
        created_by_id=dataset.created_by_id,
        created_at=dataset.created_at,
    )


def latest_event_label(event: Event) -> str:
    if event.labels:
        latest = sorted(event.labels, key=lambda label: label.created_at)[-1]
        return latest.label
    return event.type
