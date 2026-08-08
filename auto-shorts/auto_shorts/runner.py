from pathlib import Path
from typing import Dict, Any
import json

from . import transcribe, silence, scoring, align, export
from .db import update_project_status, add_clip


def run_project(project: Dict[str, Any], db_path: str, output_dir: str, dry_run: bool = True, platform: str = "YouTube Shorts", min_length: int = 15, max_length: int = 60, clean_audio: bool = False, vertical: bool = False, captions: bool = False):
    src = project["source"]
    pid = project["id"]
    update_project_status(db_path, pid, "processing")

    try:
        transcript = transcribe.transcribe(src)
        sil = silence.detect_silences(src)
        candidates = scoring.score_sentences(transcript, min_length=min_length, max_length=max_length, top_k=20)
        aligned = align.snap_to_silence(candidates, sil, transcript_path=transcript, min_length=min_length, max_length=max_length)

        manifest = {"source": src, "platform": platform, "segments": aligned}
        outdir = Path(output_dir) / f"project_{pid}" / platform.replace(" ", "_")
        outdir.mkdir(parents=True, exist_ok=True)
        manifest_path = outdir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        if dry_run:
            update_project_status(db_path, pid, "ready")
            return str(manifest_path)

        results = export.export_clips(
            src,
            aligned,
            str(outdir),
            platform=platform,
            vertical=vertical,
            captions=captions,
            clean_audio_flag=clean_audio,
        )
        # store clips
        for r in results:
            add_clip(db_path, pid, r.get("start"), r.get("end"), r.get("file"), r.get("score", 0.0), r.get("reason", ""))

        update_project_status(db_path, pid, "completed")
        return str(manifest_path)
    except Exception as exc:
        update_project_status(db_path, pid, "error")
        raise
