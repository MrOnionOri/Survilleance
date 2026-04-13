import logging
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, SessionLocal, engine, get_db
from app.models import AIModel, Camera, Event, Label, TestSession, User
from app.schemas import (
    CameraCreate,
    CameraRecordingStatus,
    CameraRead,
    CameraUpdate,
    EventCreate,
    EventRead,
    LabelCreate,
    LabelRead,
    LoginRequest,
    ManualEventCreate,
    ModelCreate,
    ModelRead,
    RecordingChunk,
    Token,
    TestSessionCreate,
    TestSessionRead,
    UserCreate,
    UserRead,
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
from app.seed import seed_admin


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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
settings.streamwatch_data_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.streamwatch_data_dir), name="media")


class StreamHub:
    def __init__(self) -> None:
        self.viewers: dict[int, set[WebSocket]] = {}

    async def add_viewer(self, camera_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.viewers.setdefault(camera_id, set()).add(websocket)

    def remove_viewer(self, camera_id: int, websocket: WebSocket) -> None:
        self.viewers.get(camera_id, set()).discard(websocket)

    async def broadcast(self, camera_id: int, frame: bytes) -> None:
        dead: list[WebSocket] = []
        for viewer in self.viewers.get(camera_id, set()).copy():
            try:
                await viewer.send_bytes(frame)
            except Exception:
                dead.append(viewer)
        for viewer in dead:
            self.remove_viewer(camera_id, viewer)


stream_hub = StreamHub()


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
    with SessionLocal() as db:
        seed_admin(db)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.websocket("/ws/cameras/{camera_id}/stream")
async def camera_stream(websocket: WebSocket, camera_id: int, token: str, mode: str = "viewer") -> None:
    with SessionLocal() as db:
        user = get_user_from_token(token, db)
        camera = db.get(Camera, camera_id)
    if not user or not camera:
        await websocket.close(code=1008)
        return

    if mode == "producer":
        if user.role.value not in {"admin", "supervisor"}:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            while True:
                frame = await websocket.receive_bytes()
                await stream_hub.broadcast(camera_id, frame)
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
    return Token(access_token=create_access_token(user.email))


@app.post("/auth/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Annotated[Session, Depends(get_db)], _: CanConfigure) -> User:
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(email=payload.email, password_hash=hash_password(payload.password), role=payload.role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.get("/auth/me", response_model=UserRead)
def me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user


@app.get("/cameras", response_model=list[CameraRead])
def list_cameras(
    db: Annotated[Session, Depends(get_db)],
    _: CanView,
    include_disabled: bool = Query(default=False),
) -> list[CameraRead]:
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
            created_at=camera.created_at,
            locked_by_test_id=locks.get(camera.id, (None, None))[0],
            locked_by_test_name=locks.get(camera.id, (None, None))[1],
        )
        for camera in cameras
    ]


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
    if _camera_locked(db, camera_id):
        raise HTTPException(status_code=409, detail="Camera is locked by a running test")
    for field, value in payload.model_dump(exclude_unset=True).items():
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
    running_tests = db.scalars(select(TestSession).where(TestSession.status == "running")).all()
    return any(camera_id in json.loads(test.camera_ids_json) for test in running_tests)


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
    tests = db.scalars(select(TestSession).order_by(desc(TestSession.started_at))).all()
    return [_test_to_read(test) for test in tests]


@app.post("/tests", response_model=TestSessionRead, status_code=status.HTTP_201_CREATED)
def create_test(payload: TestSessionCreate, db: Annotated[Session, Depends(get_db)], current_user: CanTrain) -> TestSessionRead:
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


@app.get("/events", response_model=list[EventRead])
def list_events(
    db: Annotated[Session, Depends(get_db)],
    _: CanView,
    camera_id: int | None = None,
    event_type: str | None = Query(default=None, alias="type"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[Event]:
    query = select(Event).order_by(desc(Event.timestamp)).limit(limit)
    if camera_id:
        query = query.where(Event.camera_id == camera_id)
    if event_type:
        query = query.where(Event.type == event_type)
    return list(db.scalars(query))


@app.post("/events", response_model=EventRead, status_code=status.HTTP_201_CREATED)
def create_event(payload: EventCreate, db: Annotated[Session, Depends(get_db)], _: CanTrain) -> Event:
    if not db.get(Camera, payload.camera_id):
        raise HTTPException(status_code=404, detail="Camera not found")
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
    label = Label(**payload.model_dump(), user_id=current_user.id)
    db.add(label)
    db.commit()
    db.refresh(label)
    return label


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
def list_models(db: Annotated[Session, Depends(get_db)], _: CanTrain) -> list[AIModel]:
    return list(db.scalars(select(AIModel).order_by(desc(AIModel.created_at))))


@app.post("/models", response_model=ModelRead, status_code=status.HTTP_201_CREATED)
def register_model(payload: ModelCreate, db: Annotated[Session, Depends(get_db)], _: CanTrain) -> AIModel:
    model = AIModel(**payload.model_dump())
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


@app.post("/train")
def train(_: CanTrain) -> dict[str, str]:
    return {
        "status": "queued",
        "message": "Training pipeline placeholder. Connect this endpoint to a GPU worker when the dataset is ready.",
    }
