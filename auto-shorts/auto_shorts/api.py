"""HTTP boundary for the React studio frontend.

Run with: python -m uvicorn auto_shorts.api:app --reload --port 8000
"""

from pathlib import Path
from typing import Any
import os
import shutil
import subprocess
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from auto_shorts import db
from auto_shorts import runner

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "output"
UPLOAD_ROOT = ROOT / ".auto_shorts_uploads"
DB_PATH = ROOT / "auto_shorts.db"
JOBS: dict[str, dict[str, Any]] = {}


def _video_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=400, detail="Could not determine video duration.")
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Video duration is invalid.") from exc

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
    max_seconds: int = Field(default=180, ge=1, le=180)
    selected: bool = True


class RenderRequest(BaseModel):
    source: str = ""
    resolution: str = "1080x1920"
    title: str = ""
    guest: dict[str, str] = Field(default_factory=dict)
    segments: list[Segment] = Field(default_factory=list)
    elements: list[dict[str, Any]] = Field(default_factory=list)
    logo_path: str | None = None
    logo_position: str = "Top Right"
    bottom_image_path: str | None = None
    watermark_text: str = ""
    watermark_enabled: bool = False
    watermark_position: str = "Bottom Right"
    watermark_opacity: float = Field(default=0.35, ge=0.05, le=0.8)
    frame_layout: str = "full_size_short_video"


def _resolve_workspace_path(value: str | None) -> Path | None:
    if not value:
        return None
    candidate = Path(value).expanduser()
    resolved = (candidate if candidate.is_absolute() else ROOT / candidate).resolve()
    if UPLOAD_ROOT.resolve() not in resolved.parents:
        raise HTTPException(status_code=400, detail="Asset must come from the upload directory.")
    return resolved


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
        {"name": path.name, "path": str(path.relative_to(ROOT)), "url": f"/api/video?path={path.relative_to(ROOT).as_posix()}"}
        for path in sorted(OUTPUT_ROOT.rglob("*.mp4"), key=lambda item: item.stat().st_mtime, reverse=True)
    ] if OUTPUT_ROOT.exists() else []


@app.get("/api/video")
def video(path: str) -> FileResponse:
    requested = (ROOT / path).resolve()
    output_root = OUTPUT_ROOT.resolve()
    if output_root not in requested.parents or requested.suffix.lower() != ".mp4" or not requested.is_file():
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(requested, media_type="video/mp4", filename=requested.name)


@app.post("/api/upload")
async def upload_source(file: UploadFile = File(...)) -> dict[str, str]:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "source.mp4").name
    target = UPLOAD_ROOT / f"{uuid4().hex}_{safe_name}"
    with target.open("wb") as destination:
        shutil.copyfileobj(file.file, destination)
    return {"source": str(target.relative_to(ROOT))}


@app.post("/api/upload-asset")
async def upload_asset(file: UploadFile = File(...)) -> dict[str, str]:
    return await upload_source(file)


def _run_job(job_id: str, request: RenderRequest, source: Path) -> None:
    try:
        def report(progress: int, message: str) -> None:
            JOBS[job_id] = {
                **JOBS.get(job_id, {}),
                "status": "running",
                "progress": max(0, min(100, int(progress))),
                "message": message,
            }

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
            target_duration=max((segment.max_seconds for segment in request.segments), default=60),
            manual_segments=[segment.model_dump() for segment in request.segments] or None,
            guest_info={**request.guest, "title": request.title},
            frame_layout=request.frame_layout,
            logo_path=str(_resolve_workspace_path(request.logo_path)) if request.logo_path else None,
            logo_position=request.logo_position,
            bottom_image_path=str(_resolve_workspace_path(request.bottom_image_path)) if request.bottom_image_path else None,
            watermark_text=request.watermark_text,
            watermark_enabled=request.watermark_enabled,
            watermark_position=request.watermark_position,
            watermark_opacity=request.watermark_opacity,
            layout_config=request.elements,
            model_size=os.getenv("AUTO_SHORTS_MODEL_SIZE", "tiny"),
            lightning_mode=os.getenv("AUTO_SHORTS_LIGHTNING", "true").lower() == "true",
            beam_size=1,
            word_timestamps=False,
            progress_callback=report,
        )
        JOBS[job_id] = {
            **JOBS.get(job_id, {}),
            "status": "completed",
            "progress": 100,
            "message": "Render complete",
            "manifest": manifest,
        }
    except Exception as exc:
        JOBS[job_id] = {
            **JOBS.get(job_id, {}),
            "status": "error",
            "detail": str(exc),
        }


@app.get("/api/render/{job_id}")
def render_status(job_id: str) -> dict[str, Any]:
    return JOBS.get(job_id, {"status": "unknown"})


@app.post("/api/render")
def render(request: RenderRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    try:
        width, height = (int(value) for value in request.resolution.lower().split("x", 1))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Resolution must use WIDTHxHEIGHT format.")
    if width < 2 or height < 2:
        raise HTTPException(status_code=400, detail="Resolution dimensions must be positive.")
    source = Path(request.source).expanduser()
    if not source.is_absolute():
        source = (ROOT / source).resolve()
    if not source.exists():
        raise HTTPException(status_code=400, detail="Upload or provide a valid source video path.")
    _resolve_workspace_path(request.logo_path)
    _resolve_workspace_path(request.bottom_image_path)
    duration = _video_duration(source)
    previous_end = -1.0
    for index, segment in enumerate(request.segments, start=1):
        if index > 1 and segment.start <= previous_end:
            raise HTTPException(
                status_code=400,
                detail=f"Segment {index} start must be greater than Segment {index - 1} end.",
            )
        if segment.end <= segment.start:
            raise HTTPException(status_code=400, detail=f"Segment {index} end must be greater than start.")
        if segment.end > duration:
            raise HTTPException(
                status_code=400,
                detail=f"Segment {index} end cannot exceed video duration ({duration:.1f} seconds).",
            )
        previous_end = segment.end
    job_id = uuid4().hex
    JOBS[job_id] = {
        "status": "queued",
        "progress": 0,
        "message": "Waiting to start",
        "name": source.name,
    }
    background_tasks.add_task(_run_job, job_id, request, source)
    return {"status": "queued", "job_id": job_id, "name": source.name}