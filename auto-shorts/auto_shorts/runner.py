import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from . import transcribe, silence, scoring, align, export, transitions
from .db import update_project_status, add_clip
from .logging_config import logger


class RequestedClipCountError(RuntimeError):
    """Raised when export completes but fewer clips than requested were found."""


def validate_requested_clip_count(requested: int | None, generated_results: list[dict]) -> None:
    """Fail clearly if the pipeline produced fewer clips than requested."""
    requested_count = int(requested) if requested is not None else 0
    generated_count = len(generated_results or [])
    if requested_count <= 0:
        return
    if generated_count < requested_count:
        reason = (
            f"Only {generated_count} suitable content segments were found for the requested "
            f"{requested_count} short videos."
        )
        raise RequestedClipCountError(
            f"Requested: {requested_count}\nGenerated: {generated_count}\nReason: {reason}"
        )


def run_project(project: Dict[str, Any], db_path: str, output_dir: str, dry_run: bool = True, platform: str = "YouTube Shorts", min_length: int = 15, max_length: int = 60, num_shorts: int | None = None, prioritize_length: bool = False, clean_audio: bool = False, vertical: bool = False, captions: bool = False, model_size: str = "small", beam_size: int = 1, word_timestamps: bool = False, target_duration: int | None = None, progress_callback=None, use_silence_detection: bool = False, resolution: tuple = (1080, 1920), transitions_enabled: bool = False, transitions_type: str = "zoom_in", transitions_duration: float = 1.6, transitions_min_gap: float = 6.0, transitions_threshold: float = 3.0, transitions_max_per_clip: int = 3, guest_info: Optional[Dict] = None, font_path: Optional[str] = None, lightning_mode: bool = False, add_padding: bool = True, frame_layout: str = "auto", **kwargs):
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
            language="en",
            skip_vad=lightning_mode,
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
        
        # In lightning mode, reduce scoring complexity
        if lightning_mode:
            top_k = max(int(ks) if ks else 8, int(num_shorts) if num_shorts else 8)
            use_silence_detection = False
        
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
        skip_alignment = lightning_mode or kwargs.get("force_exact_length")
        if skip_alignment or locals().get("prioritize_length") and kwargs.get("force_exact_length"):
            logger.debug(f"Alignment skip enabled (lightning={lightning_mode}) — using candidates as-is")
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

        # Main-content camera transitions — annotate the aligned clips with
        # transition offsets derived from the same scoring heuristics used for
        # short selection. This happens before the manifest is written so the
        # dry-run preview shows exactly where transitions will land.
        transitions_config = None
        if transitions_enabled:
            report(90, "Marking main-content transitions…")
            transitions_config = {
                "enabled": True,
                "type": transitions_type,
                "duration": transitions_duration,
                "min_gap": transitions_min_gap,
                "threshold": transitions_threshold,
                "max_per_clip": transitions_max_per_clip,
            }
            aligned = transitions.apply_transitions(
                aligned, transcript_data, transitions_config
            )

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
        template_config = kwargs.get("template_config")
        if not isinstance(template_config, dict):
            template_config = {}
        fast_export = kwargs.get("fast_export", False) or lightning_mode
        results = export.export_clips(
            src,
            aligned,
            str(outdir),
            platform=platform,
            vertical=vertical,
            captions=captions,
            clean_audio_flag=clean_audio,
            resolution=resolution,
            guest_info=guest_info,
            bottom_image_path=kwargs.get("bottom_image_path"),
            template_config=template_config,
            font_path=font_path or template_config.get("font_path"),
            fast_export=fast_export,
            add_padding=add_padding,
            frame_layout=frame_layout,
        )
        validate_requested_clip_count(num_shorts, results)
        # store clips
        for r in results:
            add_clip(db_path, pid, r.get("start"), r.get("end"), r.get("file"), r.get("score", 0.0), r.get("reason", ""))

        update_project_status(db_path, pid, "completed")
        report(100, "Export complete")
        return str(manifest_path)
    except RequestedClipCountError:
        # The requested count was not met, but the generated clips are valid.
        update_project_status(db_path, pid, "completed")
        raise
    except Exception as exc:
        update_project_status(db_path, pid, "error")
        logger.exception(f"Project {pid} failed while processing {src}")
        raise