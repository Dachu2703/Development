"""HTTP boundary for the React studio frontend.

Run with: python -m uvicorn auto_shorts.api:app --reload --port 8000
"""

from pathlib import Path
from typing import Any
import shutil
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from auto_shorts import db
from auto_shorts import runner

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "output"
UPLOAD_ROOT = ROOT / ".auto_shorts_uploads"
DB_PATH = ROOT / "auto_shorts.db"
JOBS: dict[str, dict[str, Any]] = {}

app = FastAPI(title="auto-shorts Studio API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Segment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    selected: bool = True


class RenderRequest(BaseModel):
    source: str = ""
    resolution: str = "1080x1920"
    title: str = ""
    guest: dict[str, str] = Field(default_factory=dict)
    segments: list[Segment] = Field(default_factory=list)
    elements: list[dict[str, Any]] = Field(default_factory=list)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/projects")
def projects() -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    return db.list_projects(str(DB_PATH))


@app.get("/api/videos")
def videos() -> list[dict[str, str]]:
    return [
        {"name": path.name, "path": str(path.relative_to(ROOT))}
        for path in sorted(OUTPUT_ROOT.rglob("*.mp4"), key=lambda item: item.stat().st_mtime, reverse=True)
    ] if OUTPUT_ROOT.exists() else []


@app.post("/api/upload")
async def upload_source(file: UploadFile = File(...)) -> dict[str, str]:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "source.mp4").name
    target = UPLOAD_ROOT / f"{uuid4().hex}_{safe_name}"
    with target.open("wb") as destination:
        shutil.copyfileobj(file.file, destination)
    return {"source": str(target.relative_to(ROOT))}


def _run_job(job_id: str, request: RenderRequest, source: Path) -> None:
    try:
        db.init_db(str(DB_PATH))
        project_id = db.create_project(str(DB_PATH), source.stem, str(source))
        project = db.get_project(str(DB_PATH), project_id)
        if project is None:
            raise RuntimeError("Could not create render project")
        width, height = (int(value) for value in request.resolution.lower().split("x", 1))
        manifest = runner.run_project(
            project,
            str(DB_PATH),
            str(OUTPUT_ROOT),
            dry_run=False,
            platform="YouTube Shorts",
            vertical=height >= width,
            resolution=(width, height),
            num_shorts=len(request.segments) or 1,
            target_duration=int(max(5, min(180, request.segments[0].end - request.segments[0].start))) if request.segments else 60,
            manual_segments=[segment.model_dump() for segment in request.segments] or None,
            guest_info={**request.guest, "title": request.title},
            frame_layout="full_size_short_video",
        )
        JOBS[job_id] = {"status": "completed", "manifest": manifest}
    except Exception as exc:
        JOBS[job_id] = {"status": "error", "detail": str(exc)}


@app.get("/api/render/{job_id}")
def render_status(job_id: str) -> dict[str, Any]:
    return JOBS.get(job_id, {"status": "unknown"})


@app.post("/api/render")
def render(request: RenderRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    source = Path(request.source).expanduser()
    if not source.is_absolute():
        source = (ROOT / source).resolve()
    if not source.exists():
        raise HTTPException(status_code=400, detail="Upload or provide a valid source video path.")
    for index, segment in enumerate(request.segments, start=1):
        if segment.end <= segment.start:
            raise HTTPException(status_code=400, detail=f"Segment {index} end must be greater than start.")
        if segment.end - segment.start > 180:
            raise HTTPException(status_code=400, detail=f"Segment {index} exceeds 180 seconds.")
    job_id = uuid4().hex
    JOBS[job_id] = {"status": "queued", "name": source.name}
    background_tasks.add_task(_run_job, job_id, request, source)
    return {"status": "queued", "job_id": job_id, "name": source.name}