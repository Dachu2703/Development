import json
import subprocess
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


def _read_transcript(path: str) -> Dict[str, Any]:
    tpath = Path(path)
    if not tpath.exists():
        raise FileNotFoundError(f"Transcript file not found: {path}")
    with open(tpath, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid transcript JSON: {path}")
    return data


def _overlapping_words(words: list[dict], clip_start: float, clip_end: float) -> list[dict]:
    """Return words overlapping a selected clip, keeping absolute timestamps."""
    return [
        word
        for word in (words or [])
        if float(word.get("end", word.get("start", 0.0))) > clip_start
        and float(word.get("start", 0.0)) < clip_end
        and str(word.get("text", "")).strip()
    ]


def _translated_words_for_clip(
    translated_data: Dict[str, Any],
    clip_start: float,
    clip_end: float,
) -> list[dict]:
    """Get English translation words for one selected clip."""
    words = translated_data.get("words") or []
    translated_words = _overlapping_words(words, clip_start, clip_end)

    # Normal faster-whisper builds provide word timestamps when requested.
    # If a model/runtime returns no word timestamps, fall back to translated
    # segment text and distribute words across the segment duration. This keeps
    # the existing export.py SRT writer usable without changing branding/layout.
    if translated_words:
        return translated_words

    fallback = []
    for segment in translated_data.get("segments") or []:
        seg_start = float(segment.get("start", 0.0))
        seg_end = float(segment.get("end", seg_start))
        if seg_end <= clip_start or seg_start >= clip_end:
            continue

        text = str(segment.get("text", "") or "").strip()
        tokens = text.split()
        if not tokens:
            continue

        start = max(clip_start, seg_start)
        end = min(clip_end, seg_end)
        if end <= start:
            continue

        step = (end - start) / len(tokens)
        for index, token in enumerate(tokens):
            ws = start + index * step
            we = end if index == len(tokens) - 1 else start + (index + 1) * step
            fallback.append(
                {
                    "start": ws,
                    "end": we,
                    "text": token,
                    "confidence": None,
                }
            )
    return fallback


def _attach_caption_words(
    aligned: list[dict],
    words: list[dict],
    field_name: str = "words",
) -> None:
    for segment in aligned:
        clip_start = float(segment["start"])
        clip_end = float(segment["end"])
        segment[field_name] = _overlapping_words(words, clip_start, clip_end)


def run_project(
    project: Dict[str, Any],
    db_path: str,
    output_dir: str,
    dry_run: bool = True,
    platform: str = "YouTube Shorts",
    min_length: int = 15,
    max_length: int = 60,
    num_shorts: int | None = None,
    prioritize_length: bool = False,
    clean_audio: bool = False,
    vertical: bool = False,
    captions: bool = False,
    model_size: str = "small",
    beam_size: int = 1,
    word_timestamps: bool = False,
    target_duration: int | None = None,
    progress_callback=None,
    use_silence_detection: bool = False,
    resolution: tuple = (1080, 1920),
    transitions_enabled: bool = False,
    transitions_type: str = "zoom_in",
    transitions_duration: float = 1.6,
    transitions_min_gap: float = 6.0,
    transitions_threshold: float = 3.0,
    transitions_max_per_clip: int = 3,
    guest_info: Optional[Dict] = None,
    font_path: Optional[str] = None,
    lightning_mode: bool = False,
    add_padding: bool = True,
    frame_layout: str = "auto",
    subtitle_mode: str = "original",
    subtitle_source_language: str = "ta",
    **kwargs,
):
    src = project["source"]
    pid = project["id"]
    update_project_status(db_path, pid, "processing")

    try:
        def report(progress: int, message: str) -> None:
            if progress_callback:
                progress_callback(progress, message)

        if target_duration is not None:
            min_length, max_length = scoring.duration_bounds(int(target_duration))
        max_length = min(int(max_length), scoring.MAX_SHORT_DURATION)
        if min_length > max_length:
            raise ValueError("min_length cannot exceed max_length")

        # ---------------------------------------------------------------
        # 1) Analyze the source in its original language.
        #    Tamil -> Tamil transcription is used for scoring/selection.
        # ---------------------------------------------------------------
        subtitle_mode_value = str(
            subtitle_mode or kwargs.get("subtitle_mode") or "original"
        ).strip().lower().replace("-", "_").replace(" ", "_")

        tamil_to_english = subtitle_mode_value in {
            "tamil_to_english",
            "ta_to_en",
            "english_translation",
            "translate_tamil",
        }

        if tamil_to_english:
            source_language = str(
                subtitle_source_language or kwargs.get("subtitle_source_language") or "ta"
            ).strip().lower()
            source_task = "transcribe"
            source_label = "Tamil"
        else:
            source_language = str(
                kwargs.get("transcription_language")
                or ("en" if subtitle_mode_value in {"original", "english"} else subtitle_source_language)
            ).strip().lower()
            source_task = "transcribe"
            source_label = source_language

        report(
            5,
            f"Transcribing source audio ({source_label})…"
        )
        transcript = transcribe.transcribe(
            src,
            model_size=model_size,
            beam_size=beam_size,
            word_timestamps=bool(word_timestamps),
            language=source_language,
            task=source_task,
            skip_vad=lightning_mode,
        )
        logger.debug(f"Source transcription output path: {transcript}")

        transcript_data = _read_transcript(transcript)
        segs = transcript_data.get("segments") or []
        words = transcript_data.get("words") or []
        logger.debug(
            f"Source transcript segments: {len(segs)}, words: {len(words)}, "
            f"language={transcript_data.get('language')}"
        )

        # ---------------------------------------------------------------
        # 2) Translation is intentionally delayed until AFTER clip
        #    selection/alignment. Translating the whole source video here
        #    doubles Whisper work for long videos.
        # ---------------------------------------------------------------
        translated_data_by_clip: Dict[int, Dict[str, Any]] = {}

        if use_silence_detection:
            report(55, "Finding natural pause boundaries…")
            sil = silence.detect_silences(src)
            if sil is None:
                logger.debug("silence.detect_silences returned None, normalizing to []")
                sil = []
            logger.debug(f"Detected silences: {len(sil)}")
        else:
            report(55, "Using transcript content boundaries (fast mode)…")
            sil = []

        ks = num_shorts if num_shorts is not None else kwargs.get("num_shorts")
        manual_windows = kwargs.get("manual_segments") or []
        top_k = int(ks) if ks else 20
        if manual_windows:
            top_k = max(top_k, len(manual_windows) * 20)

        if lightning_mode:
            top_k = max(int(ks) if ks else 8, int(num_shorts) if num_shorts else 8)
            use_silence_detection = False

        pl = (
            prioritize_length
            if prioritize_length is not None
            else bool(kwargs.get("prioritize_length", False))
        )

        report(75, "Scoring high-engagement moments…")
        if manual_windows:
            candidates = []
            for window in manual_windows:
                window_start = float(window.get("start", 0.0))
                window_end = float(window.get("end", 0.0))
                window_max = int(window.get("max_seconds", max_length))
                candidates.extend(
                    scoring.score_sentences(
                        transcript,
                        min_length=min_length,
                        max_length=window_max,
                        top_k=1,
                        prioritize_length=pl,
                        target_duration=window_max,
                        analysis_start=window_start,
                        analysis_end=window_end,
                    )
                )
        else:
            candidates = scoring.score_sentences(
                transcript,
                min_length=min_length,
                max_length=max_length,
                top_k=top_k,
                prioritize_length=pl,
                target_duration=target_duration,
            )
        if candidates is None:
            logger.debug("scoring.score_sentences returned None, normalizing to []")
            candidates = []
        logger.debug(f"Initial candidate clips: {len(candidates)}")

        report(88, "Building peak-centered clips…")
        skip_alignment = lightning_mode or kwargs.get("force_exact_length")
        if skip_alignment or (
            locals().get("prioritize_length")
            and kwargs.get("force_exact_length")
        ):
            logger.debug(
                f"Alignment skip enabled (lightning={lightning_mode}) — using candidates as-is"
            )
            aligned = candidates or []
        else:
            try:
                aligned = align.snap_to_silence(
                    candidates or [],
                    sil or [],
                    transcript_path=transcript,
                    min_length=min_length,
                    max_length=max_length,
                )
            except Exception:
                logger.exception("snap_to_silence failed — logging inputs")
                logger.debug(
                    f"candidates (first 5): "
                    f"{candidates[:5] if isinstance(candidates, list) else str(candidates)}"
                )
                logger.debug(
                    f"silences (first 5): "
                    f"{sil[:5] if isinstance(sil, list) else str(sil)}"
                )
                raise

        manual_segments = kwargs.get("manual_segments")
        if manual_segments:
            aligned = []
            for index, segment in enumerate(manual_segments, start=1):
                start = float(segment.get("start", 0.0))
                end = float(segment.get("end", 0.0))
                max_seconds = int(segment.get("max_seconds", max_length))
                if start < 0 or end <= start:
                    raise ValueError(
                        f"Manual segment {index} must have end greater than start"
                    )
                if not 1 <= max_seconds <= scoring.MAX_SHORT_DURATION:
                    raise ValueError(
                        f"Manual segment {index} max_seconds must be between 1 and {int(scoring.MAX_SHORT_DURATION)}"
                    )
                window_candidates = [
                    candidate
                    for candidate in candidates
                    if float(candidate.get("start", 0.0)) < end
                    and float(candidate.get("end", 0.0)) > start
                ]
                if window_candidates:
                    best = max(window_candidates, key=lambda item: item.get("score", 0))
                    clip_start = max(start, float(best["start"]))
                    clip_end = min(end, float(best["end"]))
                    if clip_end - clip_start > max_seconds:
                        clip_end = clip_start + max_seconds
                    aligned.append({
                        "start": clip_start,
                        "end": clip_end,
                        "reason": "best moment in analysis window",
                    })
                else:
                    aligned.append({
                        "start": start,
                        "end": min(end, start + max_seconds),
                        "reason": "analysis window fallback",
                    })

        # Attach captions without changing the selected clip boundaries.
        if captions:
            if tamil_to_english:
                total_clips = len(aligned)
                for clip_index, segment in enumerate(aligned):
                    clip_start = float(segment["start"])
                    clip_end = float(segment["end"])

                    # Translate ONLY this selected Short instead of the entire
                    # source video. faster-whisper timestamps are relative to
                    # the extracted clip, so shift them back to source time.
                    report(
                        88 + int((clip_index / max(total_clips, 1)) * 4),
                        f"Translating selected Short {clip_index + 1}/{total_clips}…",
                    )

                    # Use the source video with a time offset/duration where
                    # supported by faster-whisper. The current transcribe API
                    # accepts a video path, so create a temporary audio clip
                    # through ffmpeg and translate that short clip.
                    import tempfile

                    with tempfile.TemporaryDirectory(prefix="auto_shorts_translate_") as tmp:
                        clip_audio = Path(tmp) / f"clip_{clip_index + 1}.wav"
                        ffmpeg_cmd = [
                            "ffmpeg", "-y",
                            "-ss", str(clip_start),
                            "-t", str(max(0.1, clip_end - clip_start)),
                            "-i", str(src),
                            "-vn",
                            "-ac", "1",
                            "-ar", "16000",
                            str(clip_audio),
                        ]
                        ffmpeg_result = subprocess.run(
                            ffmpeg_cmd,
                            capture_output=True,
                            text=True,
                        )
                        if ffmpeg_result.returncode != 0:
                            raise RuntimeError(
                                "Failed to extract selected clip for translation: "
                                + (ffmpeg_result.stderr[-1000:] or "unknown ffmpeg error")
                            )

                        translated_path = transcribe.transcribe(
                            str(clip_audio),
                            cache_dir=str(Path(output_dir) / ".translation_cache"),
                            model_size=model_size,
                            beam_size=beam_size,
                            word_timestamps=True,
                            language=source_language,
                            task="translate",
                            skip_vad=lightning_mode,
                        )
                        clip_translation = _read_transcript(translated_path)

                    # Convert clip-relative timestamps back to source-video
                    # timestamps so export.py continues to write correct SRTs.
                    translated_words = []
                    for word in clip_translation.get("words") or []:
                        w = dict(word)
                        w["start"] = float(w.get("start", 0.0)) + clip_start
                        w["end"] = float(w.get("end", w["start"])) + clip_start
                        translated_words.append(w)

                    translated_data_by_clip[clip_index] = {
                        **clip_translation,
                        "words": translated_words,
                    }

                    segment["words"] = _translated_words_for_clip(
                        translated_data_by_clip[clip_index],
                        clip_start,
                        clip_end,
                    )
                    segment["subtitle_language"] = "en"
                    segment["subtitle_mode"] = "tamil_to_english"
            elif words:
                _attach_caption_words(aligned, words)
                segment_language = transcript_data.get("language") or source_language
                for segment in aligned:
                    segment["subtitle_language"] = segment_language
                    segment["subtitle_mode"] = "original"

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

        for segment in aligned:
            segment["end"] = min(
                float(segment["end"]),
                float(segment["start"]) + scoring.MAX_SHORT_DURATION,
            )

        manifest = {
            "source": src,
            "platform": platform,
            "target_duration": target_duration,
            "subtitle_mode": "tamil_to_english" if tamil_to_english else "original",
            "subtitle_language": "en" if tamil_to_english else transcript_data.get("language"),
            "segments": aligned,
        }

        outdir = (
            Path(output_dir)
            / f"project_{pid}"
            / platform.replace(" ", "_")
        )
        outdir.mkdir(parents=True, exist_ok=True)
        manifest_path = outdir / "manifest.json"

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        if dry_run:
            update_project_status(db_path, pid, "ready")
            report(100, "Preview ready")
            return str(manifest_path)

        report(92, "Exporting video clips…")
        template_config = kwargs.get("template_config")
        if not isinstance(template_config, dict):
            template_config = {}

        layout_value = (
            str(frame_layout or "auto")
            .strip()
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )
        if layout_value in {"full_size_short_video", "single", "single_frame"}:
            frame_layout = "full_size_short_video"
        elif layout_value in {
            "3_part_frame",
            "three_part_frame",
            "three_part",
            "3_part",
        }:
            frame_layout = "3_part_frame"

        fast_export = kwargs.get("fast_export", False) or lightning_mode

        # Preserve the existing branding/layout path exactly: all current
        # logo, bottom-image, watermark and template options are forwarded.
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
            logo_path=kwargs.get("logo_path"),
            logo_position=kwargs.get("logo_position", "Top Right"),
            bottom_image_path=kwargs.get("bottom_image_path"),
            template_config=template_config,
            font_path=font_path or template_config.get("font_path"),
            fast_export=fast_export,
            add_padding=add_padding,
            frame_layout=frame_layout,
            watermark_text=kwargs.get("watermark_text", ""),
            watermark_enabled=kwargs.get("watermark_enabled", False),
            watermark_position=kwargs.get("watermark_position", "Bottom Right"),
            watermark_opacity=kwargs.get("watermark_opacity", 0.35),
            watermark_softness=kwargs.get("watermark_softness", 0),
            content_scale=float(kwargs.get("content_scale", 1.0)),
            layout_config=kwargs.get("layout_config") or [],
        )

        validate_requested_clip_count(num_shorts, results)

        for r in results:
            add_clip(
                db_path,
                pid,
                r.get("start"),
                r.get("end"),
                r.get("file"),
                r.get("score", 0.0),
                r.get("reason", ""),
            )

        update_project_status(db_path, pid, "completed")
        report(100, "Export complete")
        return str(manifest_path)

    except RequestedClipCountError:
        update_project_status(db_path, pid, "completed")
        raise
    except Exception:
        update_project_status(db_path, pid, "error")
        logger.exception(f"Project {pid} failed while processing {src}")
        raise
