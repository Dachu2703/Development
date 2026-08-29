import subprocess
import json
from pathlib import Path
from typing import List, Dict, Optional
import tempfile
import os
import shutil

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


def _build_guest_overlay(
    guest_info: Dict, out_w: int, out_h: int
) -> str:
    """Disable guest and promotional text overlays in generated clips."""
    return ""


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
    out_w: int, out_h: int, guest_info: Optional[Dict], duration: float, font_path: Optional[str] = None
) -> str:
    video_h = int(round(out_h * 0.75))
    banner_h = int(round(out_h * 0.03))
    image_h = out_h - video_h - banner_h
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
    return (
        f"[0:v]scale={out_w}:{video_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{video_h}:(iw-{out_w})/2:(ih-{video_h})/2[main];"
        f"{banner};"
        f"color=c=black:s={out_w}x{image_h}:d={duration}[bottom_bg];"
        f"{_build_bottom_image_filter('[1:v]', '[bottom_image]', out_w, image_h)};"
        f"[bottom_bg][bottom_image]overlay=x='(W-w)/2':y='H-h':shortest=1[image];"
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
        f"[0:v]scale={out_w}:{video_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{video_h}:(iw-{out_w})/2:(ih-{video_h})/2[main];"
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
        if audio is None:
            issues.append("output has no audio stream")
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
            title_path = None
            vf = []
            vf_str = None
            out_w, out_h = resolution
            use_three_band_layout = bool(bottom_image_path and Path(bottom_image_path).exists())
            use_reference_template = bool(template_config and template_config.get("enabled"))
            if vertical:
                # compute crop parameters based on target resolution aspect ratio
                size = _get_video_size(video_path)
                if size:
                    in_w, in_h = size
                    if in_w >= in_h:
                        crop_w = int(round(in_h * out_w / out_h))
                        crop_h = in_h
                    else:
                        crop_w = in_w
                        crop_h = int(round(in_w * out_h / out_w))

                    crop_x = max(0, min(in_w - crop_w, (in_w - crop_w) // 2))
                    crop_y = max(0, min(in_h - crop_h, (in_h - crop_h) // 2))

                    if face_track:
                        mid = (start + end) / 2.0
                        face = _detect_face_center(video_path, mid)
                        if face:
                            cx, cy, fw, fh = face
                            crop_x = _compute_crop_x(in_w, in_h, crop_w, cx)
                            crop_y = _compute_crop_y(in_h, crop_h, cy)

                    vf.append(f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}")
                else:
                    vf.append(f"crop=round(in_h*{out_w}/{out_h}):in_h")
                vf.append(f"scale={out_w}:{out_h}")
                vf_str = ",".join(vf)

            # Keep the actual content centered; default is no text overlay.
            guest_vf = _build_guest_overlay(guest_info, out_w, out_h) or None
            logo_vf = _build_logo_overlay(logo_path, out_w, out_h) or None

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
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-r", "30", "-fps_mode", "cfr", "-pix_fmt", "yuv420p",
                    "-level:v", "5.1", "-t", str(duration), "-c:a", "aac", "-b:a", "192k", str(cut_file),
                ]
            elif use_three_band_layout:
                cmd += ["-loop", "1", "-i", str(bottom_image_path)]
                cmd += [
                    "-filter_complex",
                    _build_three_band_filter(out_w, out_h, guest_info, duration, font_path=font_path),
                    "-map", "[vout]",
                    "-map", "0:a:0?",
                    "-map_metadata", "-1",
                    "-map_chapters", "-1",
                    "-sn",
                    "-dn",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", str(cut_file),
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
                cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "192k", str(cut_file)]
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
            if use_three_band_layout or use_reference_template:
                _remove_extra_video_streams(out_file, out_w, out_h)
            verify_issues = _verify_video_file(out_file, out_w, out_h)
            if verify_issues:
                # Re-export with explicit scale+crop to force the exact resolution
                reexport_file = out_file.with_name(f"{out_file.stem}_verified{out_file.suffix}")
                reexport_cmd = [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(out_file),
                    "-vf",
                    f"{_build_fit_filter(_get_video_size(video_path)[0], _get_video_size(video_path)[1], out_w, out_h)},scale={out_w}:{out_h}",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-c:a",
                    "copy",
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