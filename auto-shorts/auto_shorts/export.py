import subprocess
from pathlib import Path
from typing import List, Dict, Optional
import tempfile
import os
import shutil

from .audio_clean import clean_audio

MAX_SHORT_DURATION = 180.0

PROJECT_TMP_ROOT = Path(__file__).resolve().parents[1] / ".auto_shorts_tmp"
PROJECT_TMP_ROOT.mkdir(parents=True, exist_ok=True)
import cv2
import urllib.request
from pathlib import Path as _Path
import subprocess
import math


def _ensure_output_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def _get_video_size(path: str):
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=p=0:s=x",
        path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    try:
        w, h = out.split('x')
        return int(w), int(h)
    except Exception:
        return None


def _extract_frame(path: str, time: float, out_path: Path) -> bool:
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(time),
        "-i",
        path,
        "-frames:v",
        "1",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode == 0 and out_path.exists()


def _create_frame_tempfile(t: float) -> Path:
    tmp_dir = PROJECT_TMP_ROOT / "frames"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return tmp_dir / f"autos_shorts_frame_{int(t)}.jpg"


def _ensure_dnn_model(cache_dir: _Path = None):
    if cache_dir is None:
        cache_dir = _Path.home() / ".cache" / "auto-shorts" / "models"
    cache_dir.mkdir(parents=True, exist_ok=True)
    proto = cache_dir / "deploy.prototxt"
    model = cache_dir / "res10_300x300_ssd_iter_140000.caffemodel"
    if proto.exists() and model.exists():
        return str(proto), str(model)
    proto_url = "https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt"
    model_url = "https://raw.githubusercontent.com/opencv/opencv_3rdparty/master/res10_300x300_ssd_iter_140000.caffemodel"
    try:
        if not proto.exists():
            urllib.request.urlretrieve(proto_url, str(proto))
        if not model.exists():
            urllib.request.urlretrieve(model_url, str(model))
        return str(proto), str(model)
    except Exception:
        return None


def _detect_face_center(path: str, t: float) -> tuple:
    tmp = _create_frame_tempfile(t)
    ok = _extract_frame(path, t, tmp)
    if not ok:
        return None
    img = cv2.imread(str(tmp))
    if img is None:
        return None
    h, w = img.shape[:2]
    model_paths = _ensure_dnn_model()
    if model_paths:
        proto, model = model_paths
        try:
            net = cv2.dnn.readNetFromCaffe(proto, model)
            blob = cv2.dnn.blobFromImage(cv2.resize(img, (300, 300)), 1.0, (300, 300), (104.0, 177.0, 123.0))
            net.setInput(blob)
            detections = net.forward()
            best = None
            best_area = 0
            for i in range(detections.shape[2]):
                conf = float(detections[0, 0, i, 2])
                if conf < 0.5:
                    continue
                box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                (x1, y1, x2, y2) = box.astype("int")
                ww = max(0, x2 - x1)
                hh = max(0, y2 - y1)
                area = ww * hh
                if area > best_area:
                    best_area = area
                    best = (x1, y1, ww, hh)
            if best is not None:
                x, y, bw, bh = best
                cx = x + bw / 2.0
                cy = y + bh / 2.0
                return (cx, cy, w, h)
        except Exception:
            pass
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4)
        if len(faces) == 0:
            return None
        x, y, ww, hh = max(faces, key=lambda r: r[2] * r[3])
        cx = x + ww / 2.0
        cy = y + hh / 2.0
        return (cx, cy, w, h)
    except Exception:
        return None


def _compute_crop_x(in_w: int, in_h: int, out_w: int, face_cx: float) -> int:
    half = out_w / 2
    left = int(max(0, min(in_w - out_w, face_cx - half)))
    return left


def _get_video_fps(path: str) -> float:
    """Read the frame rate of ``path`` via ffprobe, falling back to 30 fps."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=r_frame_rate",
        "-of",
        "csv=p=0",
        path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    raw = (proc.stdout or "").strip()
    try:
        if "/" in raw:
            num, den = raw.split("/")
            num_f, den_f = float(num), float(den)
            if den_f and num_f:
                return num_f / den_f
        val = float(raw)
        return val if val > 0 else 30.0
    except Exception:
        return 30.0


def _build_fit_filter(
    in_w: int, in_h: int, out_w: int, out_h: int, face_cx: float = None
) -> str:
    """Fit source to target using 'cover' semantics (scale then centre-crop).

    The source is never stretched or letterboxed. A face-centred crop is
    honoured when ``face_cx`` is provided.
    """
    if in_w <= 0 or in_h <= 0:
        return (
            f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h}:(iw-{out_w})/2:(ih-{out_h})/2"
        )
    in_ar = in_w / in_h
    out_ar = out_w / out_h
    if in_ar > out_ar:
        # Source wider than target: scale by height, centre-crop sides.
        return f"scale=-2:{out_h},crop={out_w}:{out_h}:(iw-{out_w})/2:0"
    # Source taller than target: scale by width, centre-crop top/bottom.
    return f"scale={out_w}:-2,crop={out_w}:{out_h}:0:(ih-{out_h})/2"


def _find_font_file() -> str:
    """Locate a system truetype font usable by ffmpeg's drawtext filter."""
    candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for c in candidates:
        if _Path(c).exists():
            return c
    return candidates[0]


def _format_srt_timestamp(seconds: float) -> str:
    """Format seconds as an SRT timestamp."""
    total_ms = max(0, int(round(float(seconds) * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


def _write_srt_for_clip(words: List[Dict], clip_start: float, clip_end: float, path: Path) -> None:
    """Write overlapping word timestamps as clip-relative SRT cues."""
    cues = []
    for word in words or []:
        text = str(word.get("text", "")).strip()
        word_start = float(word.get("start", clip_start))
        word_end = float(word.get("end", word_start))
        start = max(clip_start, word_start)
        end = min(clip_end, word_end)
        if text and end > start:
            cues.append((start - clip_start, end - clip_start, text))

    lines = []
    for index, (start, end, text) in enumerate(cues, start=1):
        lines.extend([
            str(index),
            f"{_format_srt_timestamp(start)} --> {_format_srt_timestamp(end)}",
            text,
            "",
        ])
    path.write_text("\n".join(lines), encoding="utf-8")


def _build_guest_overlay(
    guest_info: Dict, out_w: int, out_h: int
) -> str:
    """Compose drawtext filters for guest name, contact, and other info.

    The overlay is drawn into a slim semi-transparent bar at the top of the
    frame so it never covers the speaker's face (centre) or the captions
    (bottom). Font size is readably scaled to the output height (≈3.3%).
    """
    if not guest_info:
        return ""
    lines = []
    for key in ("name", "contact", "extra"):
        val = str(guest_info.get(key, "") or "").strip()
        if val:
            lines.append(val)
    if not lines:
        return ""

    fontsize = max(30, int(round(out_h * 0.033)))
    line_h = int(round(fontsize * 1.45))
    border = max(8, int(round(fontsize * 0.3)))
    font_file = _find_font_file().replace("'", "\\'")
    filters = []
    start_y = int(round(out_h * 0.03))
    for i, line in enumerate(lines):
        safe = line.replace("'", "\\'").replace("%", "\\%")
        y = start_y + i * line_h
        filters.append(
            f"drawtext=fontfile='{font_file}':"
            f"text='{safe}':fontcolor=white:fontsize={fontsize}:"
            f"box=1:boxcolor=black@0.55:boxborderw={border}:"
            f"x=20:y={y}"
        )
    return ",".join(filters)


def _verify_video_file(path: Path, expected_w: int, expected_h: int) -> List[str]:
    """Post-render verification: exact resolution, presence, audio, duration.

    Returns a list of human-readable issues. An empty list means the file
    passed every check and can be treated as playable output.
    """
    issues: List[str] = []
    if not path.exists() or path.stat().st_size == 0:
        return ["output file is missing or empty"]
    import json as _json

    probe = [
        "ffprobe", "-v", "error", "-show_streams",
        "-of", "json", str(path),
    ]
    try:
        proc = subprocess.run(probe, capture_output=True, text=True)
        if proc.returncode != 0:
            return ["output could not be opened by ffprobe"]
        data = _json.loads(proc.stdout or "{}")
        streams = data.get("streams", []) or []
        if not streams:
            return ["output contains no media streams"]
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if video is None:
            issues.append("output has no video stream")
        else:
            w = int(video.get("width", 0) or 0)
            h = int(video.get("height", 0) or 0)
            if w != expected_w or h != expected_h:
                issues.append(
                    f"resolution {w}x{h} does not match selected {expected_w}x{expected_h}"
                )
        if audio is None:
            issues.append("output has no audio stream")
    except Exception as exc:
        issues.append(f"verification failed: {exc}")
    return issues


def export_clips(
    video_path: str,
    segments: List[Dict],
    output_dir: str,
    platform: str = "YouTube Shorts",
    vertical: bool = False,
    captions: bool = False,
    clean_audio_flag: bool = False,
    face_track: bool = False,
    resolution: tuple = (1080, 1920),
    guest_info: Optional[Dict] = None,
) -> List[Dict]:
    out_dir = Path(output_dir)
    _ensure_output_dir(out_dir)
    results = []

    # try load words from transcript in segments metadata if present
    words = []

    # process each segment
    for i, seg in enumerate(segments, start=1):
        start = float(seg["start"])
        end = float(seg["end"])
        duration = end - start
        if duration <= 0:
            raise ValueError(f"Segment {i} has an invalid duration: {start}–{end}")
        if duration > MAX_SHORT_DURATION:
            raise ValueError(f"Segment {i} exceeds the {int(MAX_SHORT_DURATION)} second maximum")
        platform_tag = platform.lower().replace(" ", "_")
        out_file = out_dir / f"clip_{platform_tag}_{i:02d}.mp4"

        # create temporary working directory on the project temp root
        with tempfile.TemporaryDirectory(dir=str(PROJECT_TMP_ROOT)) as td:
            td = Path(td)
            cut_file = td / f"cut_{i:02d}.mp4"
            vf = []
            vf_str = None
            if vertical:
                # compute crop parameters based on target resolution aspect ratio
                out_w, out_h = resolution
                size = _get_video_size(video_path)
                if size:
                    in_w, in_h = size
                    # crop width to match target aspect ratio (e.g. 9:16)
                    crop_w = int(round(in_h * out_w / out_h))
                    # face tracking overrides center crop
                    if face_track:
                        # detect face at middle time
                        mid = (start + end) / 2.0
                        face = _detect_face_center(video_path, mid)
                        if face:
                            cx, cy, fw, fh = face
                            crop_x = _compute_crop_x(in_w, in_h, crop_w, cx)
                            vf.append(f"crop={crop_w}:{in_h}:{crop_x}:0")
                        else:
                            # fallback to center crop
                            crop_x = max(0, (in_w - crop_w) // 2)
                            vf.append(f"crop={crop_w}:{in_h}:{crop_x}:0")
                    else:
                        crop_x = max(0, (in_w - crop_w) // 2)
                        vf.append(f"crop={crop_w}:{in_h}:{crop_x}:0")
                else:
                    # unknown size: use responsive crop
                    vf.append(f"crop=round(in_h*{out_w}/{out_h}):in_h")
                vf.append(f"scale={out_w}:{out_h}")
                vf_str = ",".join(vf)

            # guest info overlay filter (applied after the vertical resize)
            guest_vf = _build_guest_overlay(guest_info, out_w, out_h) or None

            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                str(start),
                "-i",
                video_path,
                "-t",
                str(duration),
            ]
            if vf_str or captions or clean_audio_flag:
                # Combine all filter components into a single -vf option
                # (multiple -vf options cause FFmpeg to only use the last one)
                vf_parts = []
                if vf_str:
                    vf_parts.append(vf_str)
                subtitle_vf = ""
                if captions and seg.get("words"):
                    srt_file = td / f"clip_{i:02d}.srt"
                    _write_srt_for_clip(seg.get("words", []), start, end, srt_file)
                    subtitle_vf = f"subtitles={str(srt_file)}:force_style='Fontsize=36,PrimaryColour=&HFFFFFF&'"
                if guest_vf:
                    vf_parts.append(guest_vf)
                if subtitle_vf:
                    vf_parts.append(subtitle_vf)
                if vf_parts:
                    cmd += ["-vf", ",".join(vf_parts)]
                cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "192k", str(cut_file)]
            else:
                cmd += ["-c", "copy", str(cut_file)]

            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg cut failed for segment {i}: {proc.stderr}")

            # optionally clean audio
            if clean_audio_flag:
                cleaned = td / f"cleaned_{i:02d}.mp4"
                clean_audio(str(cut_file), str(cleaned), use_noisereduce=True)
                proc_file = cleaned
            else:
                proc_file = cut_file

            # captions
            if captions and seg.get("words"):
                srt_file = td / f"clip_{i:02d}.srt"
                _write_srt_for_clip(seg.get("words", []), start, end, srt_file)
                final_cmd = [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(proc_file),
                    "-vf",
                    f"subtitles={str(srt_file)}:force_style='Fontsize=36,PrimaryColour=&HFFFFFF&'",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-c:a",
                    "copy",
                    str(out_file),
                ]
                proc2 = subprocess.run(final_cmd, capture_output=True, text=True)
                if proc2.returncode != 0:
                    raise RuntimeError(f"ffmpeg burn captions failed for segment {i}: {proc2.stderr}")
            else:
                # move proc_file to out_file
                try:
                    # Prefer atomic replace when on same filesystem
                    os.replace(str(proc_file), str(out_file))
                except OSError as e:
                    # On cross-device moves this will fail; fall back to copy+remove
                    try:
                        shutil.copy2(str(proc_file), str(out_file))
                        os.remove(str(proc_file))
                    except Exception as e2:
                        raise RuntimeError(f"Export failed moving file: {e} -> {e2}")

            # post-render verification (hard resolution requirement)
            verify_issues = _verify_video_file(out_file, out_w, out_h)
            if verify_issues:
                # Re-export with explicit scale+crop to force the exact resolution
                reexport_cmd = [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(out_file),
                    "-vf",
                    f"{_build_fit_filter(_get_video_size(video_path)[0], _get_video_size(video_path)[1], out_w, out_h)},",
                    f"scale={out_w}:{out_h}",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-c:a",
                    "copy",
                    str(out_file),
                ]
                proc3 = subprocess.run(reexport_cmd, capture_output=True, text=True)
                if proc3.returncode != 0:
                    raise RuntimeError(f"Re-export to exact resolution failed: {proc3.stderr}")
                # Re-verify
                verify_issues = _verify_video_file(out_file, out_w, out_h)
                if verify_issues:
                    raise RuntimeError(f"Could not achieve exact resolution after re-export: {'; '.join(verify_issues)}")

            results.append({"file": str(out_file), "start": start, "end": end, "reason": seg.get("reason", "")})

    return results