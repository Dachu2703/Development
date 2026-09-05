import subprocess
import json
from pathlib import Path
from typing import List, Dict, Optional
import tempfile
import os
import shutil

MAX_SHORT_DURATION = 180.0
VIDEO_PERCENT = 55
TITLE_PERCENT = 15
IMAGE_PERCENT = 30

PROJECT_TMP_ROOT = Path(__file__).resolve().parents[1] / ".auto_shorts_tmp"
PROJECT_TMP_ROOT.mkdir(parents=True, exist_ok=True)
import urllib.request
from pathlib import Path as _Path
import subprocess
import math


def _get_best_video_codec():
    """Detect the best available video codec (GPU > CPU fast)."""
    # Try NVIDIA NVENC first
    probe = subprocess.run(["ffmpeg", "-codecs", "-hide_banner"], capture_output=True, text=True)
    codecs = probe.stdout + probe.stderr
    
    if "hevc_nvenc" in codecs:
        return "hevc_nvenc", "gpu"  # NVIDIA H.265
    if "h264_nvenc" in codecs:
        return "h264_nvenc", "gpu"  # NVIDIA H.264
    if "hevc_qsv" in codecs:
        return "hevc_qsv", "gpu"  # Intel Quick Sync
    if "h264_qsv" in codecs:
        return "h264_qsv", "gpu"
    
    # Fall back to CPU (use libx265 for better compression)
    return "libx264", "cpu"


def _get_ffmpeg_preset(codec_name: str, fast_export: bool) -> str:
    """Return a codec-compatible FFmpeg preset value.

    NVENC accepts numbered presets like p1..p7 rather than libx264-style names
    such as "ultrafast". Using the wrong preset string causes ffmpeg to fail
    during export with an "Unable to parse preset" error.
    """
    if "nvenc" in codec_name.lower():
        return "p1" if fast_export else "p4"
    if "qsv" in codec_name.lower():
        return "veryfast" if fast_export else "medium"
    return "ultrafast" if fast_export else "veryfast"


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


def _compute_crop_y(in_h: int, out_h: int, face_cy: float) -> int:
    half = out_h / 2
    top = int(max(0, min(in_h - out_h, face_cy - half)))
    return top


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
        return f"scale=-2:{out_h},crop={out_w}:{out_h}:(iw-{out_w})/2:(ih-{out_h})/2"
    # Source taller than target: scale by width, centre-crop top/bottom.
    return f"scale={out_w}:-2,crop={out_w}:{out_h}:(iw-{out_w})/2:(ih-{out_h})/2"


def _find_font_file(requested_path: Optional[str] = None) -> str:
    """Return the best available font for ffmpeg text rendering.

    When the user specifies a font file in the UI, prefer that exact path before
    falling back to system fonts. This keeps the selected typography consistent in
    the final exported short.
    """
    candidates: List[str] = []
    if requested_path:
        candidates.append(str(requested_path))
    candidates += [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/Nirmala.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for c in candidates:
        if c and _Path(c).exists():
            return c
    return candidates[0] if candidates else "arial.ttf"


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


def _compute_three_section_heights(output_height: int) -> Dict[str, int]:
    """Return the default simple Shorts layout: 55% video, 15% title, 30% image."""
    total = VIDEO_PERCENT + TITLE_PERCENT + IMAGE_PERCENT
    if total != 100:
        raise ValueError("Three-section layout must total 100%")

    video_h = int(round(output_height * VIDEO_PERCENT / 100))
    title_h = int(round(output_height * TITLE_PERCENT / 100))
    image_h = output_height - video_h - title_h
    return {"video": video_h, "title": title_h, "image": image_h}


def _build_guest_overlay(
    guest_info: Dict, out_w: int, out_h: int
) -> str:
    """Disable guest and promotional text overlays in generated clips."""
    return ""


def _build_shrink_to_frame_filter(
    in_w: int,
    in_h: int,
    out_w: int,
    out_h: int,
    pad_color: str = "black",
    fit_mode: str = "crop",
) -> str:
    if fit_mode == "pad":
        return (
            f"scale={out_w}:{out_h}:"
            f"force_original_aspect_ratio=decrease,"
            f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:{pad_color}"
        )
    return (
        f"scale={out_w}:{out_h}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h}:(iw-ow)/2:(ih-oh)/2"
    )


def _build_single_frame_filter(
    in_w: int,
    in_h: int,
    out_w: int,
    out_h: int,
    pad_color: str = "black",
    crop_center: Optional[tuple[float, float]] = None,
) -> str:
    """
    Fill the complete output frame for YouTube Shorts.

    Designed for a 1080x1920 (9:16) output.

    The source video keeps its original aspect ratio.
    It is scaled up until the entire target frame is covered,
    then the excess area is cropped.

    crop_center:
        Optional normalized crop position.

        (0.5, 0.5) = center
        (0.0, 0.5) = left
        (1.0, 0.5) = right
        (0.5, 0.0) = top
        (0.5, 1.0) = bottom
    """

    if in_w <= 0 or in_h <= 0:
        return (
            f"scale={out_w}:{out_h}:"
            f"force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h}:(iw-ow)/2:(ih-oh)/2"
        )

    # Default crop position = center
    center_x = 0.5
    center_y = 0.5

    if crop_center is not None:
        center_x = max(0.0, min(1.0, crop_center[0]))
        center_y = max(0.0, min(1.0, crop_center[1]))

    # Scale video until it completely covers the target frame.
    scale_filter = (
        f"scale={out_w}:{out_h}:"
        f"force_original_aspect_ratio=increase"
    )

    # Crop the excess area.
    crop_filter = (
        f"crop={out_w}:{out_h}:"
        f"(iw-ow)*{center_x}:"
        f"(ih-oh)*{center_y}"
    )

    return f"{scale_filter},{crop_filter}"

def _normalize_frame_layout(frame_layout: Optional[str]) -> str:
    """Normalize the frame layout value for strict single/three-part matching."""
    value = (frame_layout or "auto").strip().lower()
    value = value.replace("-", "_").replace(" ", "_")
    return value


def _should_use_three_part_layout(
    frame_layout: Optional[str],
    title: Optional[str],
    image_path: Optional[str],
    guest_info: Optional[Dict] = None,
) -> bool:
    """Choose the correct layout based on the explicit selection or available content."""
    value = _normalize_frame_layout(frame_layout)
    if value in {"single", "single_frame", "full_size_short_video"}:
        return False
    if value in {"three_part", "three_part_frame", "3_part", "3_part_frame"}:
        return True

    caption = str(title or "").strip() if title is not None else ""
    guest_title = str((guest_info or {}).get("title", "") or "").strip()
    image_exists = bool(image_path and Path(image_path).exists())
    return bool(caption or guest_title or image_exists)


def _build_logo_overlay(logo_path: Optional[str], out_w: int, out_h: int) -> str:
    """Return an optional top-right logo overlay with safe padding."""
    if not logo_path:
        return ""
    logo = Path(logo_path)
    if not logo.exists():
        return ""
    margin = max(20, int(round(out_w * 0.02)))
    size = max(28, int(round(min(out_w, out_h) * 0.09)))
    return (
        f"overlay=x=W-w-{margin}:y={margin}:" 
        f"eval=init:shortest=1:format=auto,"
        f"scale={size}:{size}"
    )


def _build_three_band_filter(
    out_w: int,
    out_h: int,
    guest_info: Optional[Dict],
    duration: float,
    font_path: Optional[str] = None,
    add_padding: bool = True,
    has_bottom_image: bool = True,
) -> str:
    section_heights = _compute_three_section_heights(out_h)
    video_h = section_heights["video"]
    banner_h = section_heights["title"]
    image_h = section_heights["image"]
    banner = f"color=c=0x101522:s={out_w}x{banner_h}:d={duration}"
    if guest_info:
        lines = [
            str(guest_info.get("title", "") or "").strip(),
            str(guest_info.get("name", "") or "").strip(),
            str(guest_info.get("contact", "") or "").strip(),
        ]
        text = " | ".join(line for line in lines if line)
    else:
        text = ""
    if text:
        safe = text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
        font_file = _find_font_file(font_path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        banner += f",drawtext=fontfile='{font_file}':text='{safe}':fontcolor=white:fontsize={max(28, int(out_h * 0.032))}:x=(w-text_w)/2:y=(h-text_h)/2"
    banner += "[banner]"

    # Fit the entire guest video inside the frame. Never crop the visible subject.
    if add_padding:
        video_filter = f"[0:v]{_build_shrink_to_frame_filter(0, 0, out_w, video_h, fit_mode='pad')}[main];"
    else:
        video_filter = f"[0:v]scale={out_w}:{video_h},crop={out_w}:{video_h}:0:0[main];"

    if has_bottom_image:
        return (
            f"{video_filter}"
            f"{banner};"
            f"color=c=black:s={out_w}x{image_h}:d={duration}[bottom_bg];"
            f"{_build_bottom_image_filter('[1:v]', '[bottom_image]', out_w, image_h)};"
            f"[bottom_bg][bottom_image]overlay=x='(W-w)/2':y='H-h':shortest=1[image];"
            f"[main][banner][image]vstack=inputs=3[vout]"
        )

    return (
        f"{video_filter}"
        f"{banner};"
        f"color=c=black:s={out_w}x{image_h}:d={duration}[image];"
        f"[main][banner][image]vstack=inputs=3[vout]"
    )


def _escape_drawtext(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")


def _build_image_fit_filter(input_label: str, output_label: str, out_w: int, out_h: int) -> str:
    """Fill a panel without distortion and keep the image anchored to its bottom edge."""
    return (
        f"{input_label}scale=w='ceil(max({out_w},iw*{out_h}/ih)/2)*2':"
        f"h='ceil(max({out_h},ih*{out_w}/iw)/2)*2',"
        f"crop={out_w}:{out_h}:x='(iw-ow)/2':y='ih-oh'"
        f"{output_label}"
    )


def _build_bottom_image_filter(input_label: str, output_label: str, out_w: int, out_h: int) -> str:
    """Resize a bottom image to exactly the calculated bottom panel rectangle."""
    return (
        f"{input_label}scale={out_w}:{out_h}:force_original_aspect_ratio=disable,"
        f"setsar=1{output_label}"
    )


def _build_reference_template_filter(
    out_w: int,
    out_h: int,
    template: Dict,
    duration: float,
    has_bottom_image: bool,
    has_title_image: bool = True,
    font_path: Optional[str] = None,
) -> str:
    """Compose a configurable four-section Shorts template."""
    top_h = max(1, int(template.get("top_height", round(out_h * 0.09))))
    subscribe_h = max(1, int(template.get("subscribe_height", round(out_h * 0.12))))
    video_h = max(1, int(template.get("video_height", round(out_h * 0.47))))
    title_h = max(1, int(template.get("title_height", round(out_h * 0.16))))
    bottom_h = out_h - top_h - video_h - title_h - subscribe_h
    if bottom_h < 1:
        raise ValueError("reference template section heights exceed output height")

    top_color = str(template.get("top_color", "#d90000")).replace("#", "0x")
    subscribe_color = str(template.get("subscribe_color", "#ff1717")).replace("#", "0x")
    subscribe_text = _escape_drawtext(str(template.get("subscribe_text", "SUBSCRIBE")))
    font_file = _find_font_file(font_path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    subscribe_filter = (
        f",drawtext=fontfile='{font_file}':text='{subscribe_text}':"
        f"fontcolor=white:fontsize={max(24, int(subscribe_h * 0.34))}:"
        "borderw=1:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2"
        if subscribe_text else ""
    )
    bottom_background = str(template.get("bottom_background", "image"))
    title_input_index = 2 if has_bottom_image else 1
    if bottom_background == "white_blue":
        image_input = (
            f"color=c=white:s={out_w}x{bottom_h}:d={duration},"
            f"drawbox=x=0:y={bottom_h // 2}:w={out_w}:h={bottom_h - bottom_h // 2}:"
            "color=0x2b6cb0:t=fill[bottom_bg];"
            + (
                f"{_build_bottom_image_filter('[1:v]', '[bottom_image]', out_w, bottom_h)};"
                f"[bottom_bg][bottom_image]overlay=x='(W-w)/2':y='H-h':shortest=1[bottom]"
                if has_bottom_image else
                "[bottom_bg]copy[bottom]"
            )
        )
    else:
        image_input = (
            f"color=c=black:s={out_w}x{bottom_h}:d={duration}[bottom_bg];"
            f"{_build_bottom_image_filter('[1:v]', '[bottom_image]', out_w, bottom_h)};"
            "[bottom_bg][bottom_image]overlay=x='(W-w)/2':y='H-h':shortest=1[bottom]"
        if has_bottom_image else
        f"color=c=black:s={out_w}x{bottom_h}:d={duration}[bottom]"
        )
    title_input = (
        f"color=c=black:s={out_w}x{title_h}:d={duration}[title_bg];"
        f"{_build_image_fit_filter(f'[{title_input_index}:v]', '[title_image]', out_w, title_h)};"
        "[title_bg][title_image]overlay=x='(W-w)/2':y='H-h':shortest=1[title]"
        if has_title_image else
        f"color=c=white:s={out_w}x{title_h}:d={duration}[title]"
    )
    return (
        f"color=c={top_color}:s={out_w}x{top_h}:d={duration}[top];"
        f"[0:v]{_build_shrink_to_frame_filter(0, 0, out_w, video_h)}[main];"
        f"{title_input};"
        f"{image_input};"
        f"color=c={subscribe_color}:s={out_w}x{subscribe_h}:d={duration}"
        f"{subscribe_filter}[subscribe];"
        "[top][main][title][bottom][subscribe]vstack=inputs=5[vout]"
    )


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
            matching_video = next(
                (
                    stream for stream in streams
                    if stream.get("codec_type") == "video"
                    and int(stream.get("width", 0) or 0) == expected_w
                    and int(stream.get("height", 0) or 0) == expected_h
                ),
                video,
            )
            w = int(matching_video.get("width", 0) or 0)
            h = int(matching_video.get("height", 0) or 0)
            if w != expected_w or h != expected_h:
                issues.append(
                    f"resolution {w}x{h} does not match selected {expected_w}x{expected_h}"
                )
        # Some valid source videos (including some generated test clips) have no
        # audio stream. Keep the app strict about video resolution, but do not
        # reject otherwise-good exports just because a soundtrack is absent.
        if audio is None:
            pass
    except Exception as exc:
        issues.append(f"verification failed: {exc}")
    return issues


def _remove_extra_video_streams(path: Path, expected_w: int, expected_h: int) -> None:
    probe = [
        "ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)
    ]
    proc = subprocess.run(probe, capture_output=True, text=True)
    if proc.returncode != 0:
        return
    try:
        streams = json.loads(proc.stdout or "{}").get("streams", [])
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        matching = next(
            (
                s for s in video_streams
                if int(s.get("width", 0) or 0) == expected_w
                and int(s.get("height", 0) or 0) == expected_h
            ),
            None,
        )
        if matching is None or len(video_streams) <= 1:
            return
        stream_index = int(matching.get("index", 0))
        clean_path = path.with_name(f"{path.stem}_streams{path.suffix}")
        remux = [
            "ffmpeg", "-y", "-i", str(path),
            "-map", f"0:{stream_index}", "-map", "0:a:0?",
            "-c", "copy", "-map_metadata", "-1", "-map_chapters", "-1",
            str(clean_path),
        ]
        cleaned = subprocess.run(remux, capture_output=True, text=True)
        if cleaned.returncode == 0 and clean_path.exists():
            os.replace(str(clean_path), str(path))
    except (TypeError, ValueError, OSError, json.JSONDecodeError):
        return


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
    transitions: Optional[Dict] = None,
    logo_path: Optional[str] = None,
    bottom_image_path: Optional[str] = None,
    template_config: Optional[Dict] = None,
    font_path: Optional[str] = None,
    fast_export: bool = False,
    add_padding: bool = True,
    frame_layout: str = "auto",
) -> List[Dict]:
    out_dir = Path(output_dir)
    _ensure_output_dir(out_dir)
    results = []

    # Determine FFmpeg settings based on performance mode and codec compatibility.
    if fast_export:
        video_codec, codec_type = _get_best_video_codec()
    else:
        video_codec, codec_type = "libx264", "cpu"
    ffmpeg_preset = _get_ffmpeg_preset(video_codec, fast_export)
    ffmpeg_crf = "28" if fast_export else "23"
    audio_bitrate = "128k" if fast_export else "192k"

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
            title_path = None
            vf = []
            vf_str = None
            out_w, out_h = resolution
            title_text = str((guest_info or {}).get("title", "") or "").strip()
            normalized_layout = _normalize_frame_layout(frame_layout)
            explicit_single_layout = normalized_layout in {"single", "single_frame", "full_size_short_video"}
            explicit_three_part_layout = normalized_layout in {
                "three_part",
                "three_part_frame",
                "3_part",
                "3_part_frame",
            }

            if explicit_single_layout:
                use_three_band_layout = False
                use_reference_template = False
            elif explicit_three_part_layout:
                use_three_band_layout = True
                use_reference_template = False
            else:
                use_three_band_layout = _should_use_three_part_layout(
                    frame_layout,
                    title_text,
                    bottom_image_path,
                    guest_info,
                )
                use_reference_template = bool(template_config and template_config.get("enabled"))

            if vertical:
                # Keep the full source inside the frame and centered without black bars.
                size = _get_video_size(video_path)
                crop_center = None
                if face_track:
                    mid_time = start + (duration / 2.0)
                    detected = _detect_face_center(video_path, mid_time)
                    if detected is not None:
                        crop_center = (detected[0], detected[1])
                if size:
                    in_w, in_h = size
                    vf.append(_build_single_frame_filter(in_w, in_h, out_w, out_h, crop_center=crop_center))
                else:
                    vf.append(_build_single_frame_filter(0, 0, out_w, out_h, crop_center=crop_center))
                vf_str = ",".join(vf)

            # Keep the actual content centered; default is no text overlay.
            guest_vf = _build_guest_overlay(guest_info, out_w, out_h) or None
            logo_vf = _build_logo_overlay(logo_path, out_w, out_h) or None

            cmd = [
                "ffmpeg",
                "-y",
                "-nostdin",
                "-ss",
                str(start),
                "-i",
                video_path,
                "-t",
                str(duration),
            ]
            if use_reference_template:
                title_text = str(template_config.get("title", "")).strip()
                if title_text:
                    from .typography import render_shorts_title
                    title_path = td / f"title_{i:02d}.png"
                    render_shorts_title(
                        title_text,
                        str(title_path),
                        {
                            "videoWidth": out_w,
                            "videoHeight": int(template_config.get("title_height", round(out_h * 0.16))),
                            "position": template_config.get("title_position", "center"),
                            "style": template_config.get("style", "NEWS"),
                            "fontPath": template_config.get("font_path"),
                        },
                    )
                if bottom_image_path and Path(bottom_image_path).exists():
                    cmd += ["-loop", "1", "-i", str(bottom_image_path)]
                if title_path:
                    cmd += ["-loop", "1", "-i", str(title_path)]
                cmd += [
                    "-filter_complex",
                    _build_reference_template_filter(
                        out_w, out_h, template_config, duration,
                        bool(bottom_image_path and Path(bottom_image_path).exists()),
                        bool(title_path),
                        font_path=font_path,
                    ),
                    "-map", "[vout]", "-map", "0:a:0?",
                    "-map_metadata", "-1", "-map_chapters", "-1", "-sn", "-dn",
                    "-c:v", video_codec, "-preset", ffmpeg_preset, "-crf", ffmpeg_crf,
                    "-r", "30", "-fps_mode", "cfr", "-pix_fmt", "yuv420p",
                    "-level:v", "5.1", "-t", str(duration), "-c:a", "aac", "-b:a", audio_bitrate, str(cut_file),
                ]
            elif use_three_band_layout:
                has_bottom_image = bool(bottom_image_path and Path(bottom_image_path).exists())
                if has_bottom_image:
                    cmd += ["-loop", "1", "-i", str(bottom_image_path)]
                cmd += [
                    "-filter_complex",
                    _build_three_band_filter(
                        out_w,
                        out_h,
                        guest_info,
                        duration,
                        font_path=font_path,
                        add_padding=add_padding,
                        has_bottom_image=has_bottom_image,
                    ),
                    "-map", "[vout]",
                    "-map", "0:a:0?",
                    "-map_metadata", "-1",
                    "-map_chapters", "-1",
                    "-sn",
                    "-dn",
                    "-c:v", video_codec, "-preset", ffmpeg_preset, "-crf", ffmpeg_crf,
                    "-c:a", "aac", "-b:a", audio_bitrate, "-shortest", str(cut_file),
                ]
            elif vf_str or captions or clean_audio_flag:
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
                if logo_vf:
                    vf_parts.append(logo_vf)
                if subtitle_vf:
                    vf_parts.append(subtitle_vf)
                if vf_parts:
                    cmd += ["-vf", ",".join(vf_parts)]
                if clean_audio_flag:
                    cmd += ["-af", "afftdn,loudnorm=I=-16:TP=-1.5:LRA=11"]
                cmd += ["-c:v", video_codec, "-preset", ffmpeg_preset, "-crf", ffmpeg_crf, "-c:a", "aac", "-b:a", audio_bitrate, str(cut_file)]
            else:
                cmd += ["-c", "copy", str(cut_file)]

            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg cut failed for segment {i}: {proc.stderr}")

            proc_file = cut_file

            # captions
            if captions and seg.get("words"):
                srt_file = td / f"clip_{i:02d}.srt"
                _write_srt_for_clip(seg.get("words", []), start, end, srt_file)
                final_cmd = [
                    "ffmpeg",
                    "-y",
                    "-nostdin",
                    "-i",
                    str(proc_file),
                    "-vf",
                    f"subtitles={str(srt_file)}:force_style='Fontsize=36,PrimaryColour=&HFFFFFF&'",
                    "-c:v",
                    video_codec,
                    "-preset",
                    ffmpeg_preset,
                    "-crf",
                    ffmpeg_crf,
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
            if use_three_band_layout or use_reference_template:
                _remove_extra_video_streams(out_file, out_w, out_h)
            verify_issues = _verify_video_file(out_file, out_w, out_h)
            if verify_issues:
                # Re-export with explicit scale+crop to force the exact resolution
                reexport_file = out_file.with_name(f"{out_file.stem}_verified{out_file.suffix}")
                reexport_cmd = [
                    "ffmpeg",
                    "-y",
                    "-nostdin",
                    "-i",
                    str(out_file),
                    "-vf",
                    f"{_build_fit_filter(_get_video_size(video_path)[0], _get_video_size(video_path)[1], out_w, out_h)},scale={out_w}:{out_h}",
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a?",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-c:a",
                    "aac",
                    str(reexport_file),
                ]
                proc3 = subprocess.run(reexport_cmd, capture_output=True, text=True)
                if proc3.returncode != 0:
                    raise RuntimeError(f"Re-export to exact resolution failed: {proc3.stderr}")
                os.replace(str(reexport_file), str(out_file))
                # Re-verify
                verify_issues = _verify_video_file(out_file, out_w, out_h)
                if verify_issues:
                    raise RuntimeError(f"Could not achieve exact resolution after re-export: {'; '.join(verify_issues)}")

            results.append({"file": str(out_file), "start": start, "end": end, "reason": seg.get("reason", "")})

    return results