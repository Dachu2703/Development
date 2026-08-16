import json
import logging
from pathlib import Path
from typing import Dict, Any

from . import transcribe, silence, scoring, align, export
from .db import update_project_status, add_clip
from .logging_config import logger


def run_project(project: Dict[str, Any], db_path: str, output_dir: str, dry_run: bool = True, platform: str = "YouTube Shorts", min_length: int = 15, max_length: int = 60, num_shorts: int | None = None, prioritize_length: bool = False, clean_audio: bool = False, vertical: bool = False, captions: bool = False, model_size: str = "small", beam_size: int = 1, word_timestamps: bool = False, target_duration: int | None = None, progress_callback=None, use_silence_detection: bool = False, **kwargs):
    src = project["source"]
    pid = project["id"]
    update_project_status(db_path, pid, "processing")

    try:
        def report(progress: int, message: str) -> None:
            if progress_callback:
                progress_callback(progress, message)

        # This is the single duration policy used by scoring, alignment, and
        # export. Keeping it here prevents UI values being silently replaced by
        # a platform default later in the pipeline.
        if target_duration is not None:
            min_length, max_length = scoring.duration_bounds(int(target_duration))
        max_length = min(int(max_length), scoring.MAX_SHORT_DURATION)
        if min_length > max_length:
            raise ValueError("min_length cannot exceed max_length")
        # Transcribe and validate outputs step-by-step with defensive checks and logging
        report(5, "Transcribing audio…")
        transcript = transcribe.transcribe(
            src,
            model_size=model_size,
            beam_size=beam_size,
            word_timestamps=word_timestamps,
        )
        logger.debug(f"Transcription output path: {transcript}")

        # inspect transcript JSON early to ensure it is valid
        try:
            import json
            from pathlib import Path
            tpath = Path(transcript)
            if not tpath.exists():
                logger.warning(f"Transcript file not found: {transcript}")
                transcript_data = {}
            else:
                with open(tpath, 'r', encoding='utf-8') as tf:
                    transcript_data = json.load(tf)
            segs = transcript_data.get('segments') or []
            words = transcript_data.get('words') or []
            logger.debug(f"Transcript segments: {len(segs)}, words: {len(words)}")
        except Exception as e:
            logger.exception("Failed to read/parse transcript JSON")
            transcript_data = {}
            segs = []
            words = []

        if use_silence_detection:
            report(55, "Finding natural pause boundaries…")
            sil = silence.detect_silences(src)
            if sil is None:
                logger.debug("silence.detect_silences returned None, normalizing to []")
                sil = []
            logger.debug(f"Detected silences: {len(sil)}")
        else:
            # Whisper segment boundaries generally occur at speech/pause
            # boundaries. This avoids a second, full-length FFmpeg scan during
            # a preview; users can opt into the slower fine-tuning pass.
            report(55, "Using transcript content boundaries (fast mode)…")
            sil = []

        # determine how many top candidates to pick
        # accept num_shorts either via explicit param or via kwargs for backward compatibility
        ks = num_shorts if num_shorts is not None else kwargs.get("num_shorts")
        top_k = int(ks) if ks else 20
        pl = prioritize_length if prioritize_length is not None else bool(kwargs.get("prioritize_length", False))
        report(75, "Scoring high-engagement moments…")
        candidates = scoring.score_sentences(
            transcript, min_length=min_length, max_length=max_length, top_k=top_k,
            prioritize_length=pl, target_duration=target_duration,
        )
        if candidates is None:
            logger.debug("scoring.score_sentences returned None, normalizing to []")
            candidates = []
        logger.debug(f"Initial candidate clips: {len(candidates)}")

        # Ensure align receives valid iterables
        # If forcing exact lengths, skip silence/word snapping to preserve exact windows
        report(88, "Building peak-centered clips…")
        if kwargs.get("force_exact_length") or locals().get("prioritize_length") and kwargs.get("force_exact_length"):
            logger.debug("force_exact_length enabled — skipping snap_to_silence")
            aligned = candidates or []
        else:
            try:
                aligned = align.snap_to_silence(candidates or [], sil or [], transcript_path=transcript, min_length=min_length, max_length=max_length)
            except Exception:
                logger.exception("snap_to_silence failed — logging inputs")
                logger.debug(f"candidates (first 5): {candidates[:5] if isinstance(candidates, list) else str(candidates)}")
                logger.debug(f"silences (first 5): {sil[:5] if isinstance(sil, list) else str(sil)}")
                raise

        # The exporter needs clip-local word timestamps to make SRT captions.
        # Preserve only words that overlap each selected clip so captions stay
        # in sync and the manifest remains compact.
        if captions and words:
            for segment in aligned:
                clip_start = float(segment["start"])
                clip_end = float(segment["end"])
                segment["words"] = [
                    word for word in words
                    if float(word.get("end", word.get("start", 0.0))) > clip_start
                    and float(word.get("start", 0.0)) < clip_end
                ]

        # A final guard protects callers that bypass the UI or use an old API.
        for segment in aligned:
            segment["end"] = min(float(segment["end"]), float(segment["start"]) + scoring.MAX_SHORT_DURATION)
        manifest = {"source": src, "platform": platform, "target_duration": target_duration, "segments": aligned}
        outdir = Path(output_dir) / f"project_{pid}" / platform.replace(" ", "_")
        outdir.mkdir(parents=True, exist_ok=True)
        manifest_path = outdir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        if dry_run:
            update_project_status(db_path, pid, "ready")
            report(100, "Preview ready")
            return str(manifest_path)

        report(92, "Exporting video clips…")
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
        report(100, "Export complete")
        return str(manifest_path)
    except Exception as exc:
        update_project_status(db_path, pid, "error")
        logger.exception(f"Project {pid} failed while processing {src}")
        raise
