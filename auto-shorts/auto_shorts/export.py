import subprocess
from pathlib import Path
from typing import List, Dict
import tempfile
import os

from .audio_clean import clean_audio
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


def _ensure_dnn_model(cache_dir: _Path = None):
    if cache_dir is None:
        cache_dir = _Path.home() / ".cache" / "auto-shorts" / "models"
    cache_dir.mkdir(parents=True, exist_ok=True)
    proto = cache_dir / "deploy.prototxt"
    model = cache_dir / "res10_300x300_ssd_iter_140000.caffemodel"
    if proto.exists() and model.exists():
        return str(proto), str(model)
    # Download from OpenCV's GitHub if missing
    proto_url = "https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt"
    model_url = "https://raw.githubusercontent.com/opencv/opencv_3rdparty/master/res10_300x300_ssd_iter_140000.caffemodel"
    try:
        if not proto.exists():
            urllib.request.urlretrieve(proto_url, str(proto))
        if not model.exists():
            urllib.request.urlretrieve(model_url, str(model))
        return str(proto), str(model)
    except Exception:
        # if download fails, return None to allow fallback
        return None


def _detect_face_center(path: str, t: float) -> tuple:
    # extract frame and run OpenCV DNN face detector with Haar fallback
    tmp = Path(tempfile.gettempdir()) / f"autos_shorts_frame_{int(t)}.jpg"
    ok = _extract_frame(path, t, tmp)
    if not ok:
        return None
    img = cv2.imread(str(tmp))
    if img is None:
        return None
    h, w = img.shape[:2]
    # try DNN model first
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
    # fallback to Haar cascade
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
    # center crop horizontally around face_cx ensuring crop within bounds
    half = out_w / 2
    left = int(max(0, min(in_w - out_w, face_cx - half)))
    return left


def _format_srt_time(seconds: float) -> str:
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hrs:02d}:{mins:02d}:{secs:06.3f}".replace(".", ",")


def _write_srt_for_clip(words: List[Dict], clip_start: float, clip_end: float, srt_path: Path):
    # Collect words in clip and group into lines of ~3s
    items = []
    idx = 1
    cur_start = None
    cur_text = []
    cur_end = None
    for w in words:
        ws = float(w.get("start", 0.0))
        we = float(w.get("end", ws))
        if ws < clip_start or ws > clip_end:
            continue
        if cur_start is None:
            cur_start = ws
        cur_end = we
        cur_text.append(w.get("text", ""))
        # flush if >3s
        if cur_end - cur_start >= 3.0:
            items.append((cur_start - clip_start, cur_end - clip_start, " ".join(cur_text)))
            cur_start = None
            cur_text = []
            cur_end = None
    if cur_text and cur_start is not None:
        items.append((cur_start - clip_start, cur_end - clip_start, " ".join(cur_text)))

    with open(srt_path, "w", encoding="utf-8") as f:
        for i, (s, e, t) in enumerate(items, start=1):
            f.write(f"{i}\n")
            f.write(f"{_format_srt_time(s)} --> {_format_srt_time(e)}\n")
            f.write(t + "\n\n")


def export_clips(
    video_path: str,
    segments: List[Dict],
    output_dir: str,
    platform: str = "YouTube Shorts",
    vertical: bool = False,
    captions: bool = False,
    clean_audio_flag: bool = False,
    face_track: bool = False,
) -> List[Dict]:
    out_dir = Path(output_dir)
    _ensure_output_dir(out_dir)
    results = []

    # try load words from transcript in segments metadata if present
    words = []

    # process each segment
    for i, seg in enumerate(segments, start=1):
        start = seg["start"]
        end = seg["end"]
        platform_tag = platform.lower().replace(" ", "_")
        out_file = out_dir / f"clip_{platform_tag}_{i:02d}.mp4"

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            cut_file = td / f"cut_{i:02d}.mp4"
            vf = []
            vf_str = None
            if vertical:
                # compute crop parameters
                size = _get_video_size(video_path)
                if size:
                    in_w, in_h = size
                    out_w = int(round(in_h * 9.0 / 16.0))
                    # face tracking overrides center crop
                    if face_track:
                        # detect face at middle time
                        mid = (start + end) / 2.0
                        face = _detect_face_center(video_path, mid)
                        if face:
                            cx, cy, fw, fh = face
                            crop_x = _compute_crop_x(in_w, in_h, out_w, cx)
                            vf.append(f"crop={out_w}:{in_h}:{crop_x}:0")
                        else:
                            # fallback to center crop
                            crop_x = max(0, (in_w - out_w) // 2)
                            vf.append(f"crop={out_w}:{in_h}:{crop_x}:0")
                    else:
                        crop_x = max(0, (in_w - out_w) // 2)
                        vf.append(f"crop={out_w}:{in_h}:{crop_x}:0")
                else:
                    # unknown size: use responsive crop
                    vf.append("crop=round(in_h*9/16):in_h")
                vf.append("scale=1080:1920")
                vf_str = ",".join(vf)

            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                str(start),
                "-to",
                str(end),
                "-i",
                video_path,
            ]
            if vf_str or captions or clean_audio_flag:
                # re-encode path
                if vf_str:
                    cmd += ["-vf", vf_str]
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
                os.replace(str(proc_file), str(out_file))

            results.append({"file": str(out_file), "start": start, "end": end, "reason": seg.get("reason", "")})

    return results

