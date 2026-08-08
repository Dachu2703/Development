import hashlib
import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, List

from .logging_config import logger


def _ffprobe_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        return 0.0
    try:
        return float(out.stdout.strip() or 0.0)
    except Exception:
        return 0.0


def _cache_key_for(path: Path) -> str:
    st = path.stat()
    key_src = f"{path.resolve()}::{st.st_mtime_ns}::{st.st_size}"
    return hashlib.sha1(key_src.encode()).hexdigest()


def transcribe(video_path: str, cache_dir: str = None, model_size: str = "small") -> str:
    """Transcribe `video_path` with `faster-whisper` and cache results to JSON.

    Returns path to the cached transcript JSON. The JSON contains segments and word-level timestamps.
    """
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        raise RuntimeError(
            "faster-whisper is required for transcription. Install with `pip install faster-whisper`."
        ) from exc

    src = Path(video_path)
    if cache_dir is None:
        cache_dir = Path.home() / ".cache" / "auto-shorts"
    else:
        cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    key = _cache_key_for(src)
    out_path = cache_dir / f"{src.stem}-{key}.transcript.json"
    if out_path.exists():
        return str(out_path)

    # instantiate model (CPU by default)
    compute_type = "int8"
    try:
        model = WhisperModel(model_size, device="cpu", compute_type=compute_type)
        logger.debug(f"faster-whisper using compute_type={compute_type} device=cpu model={model_size}")
    except Exception as exc:
        compute_type = "default"
        logger.warning(f"faster-whisper compute_type={compute_type} failed, falling back to default: {exc}")
        model = WhisperModel(model_size, device="cpu")
        logger.debug(f"faster-whisper fallback to compute_type={compute_type} device=cpu model={model_size}")

    segments = []
    words_all: List[Dict] = []
    # faster-whisper allows streaming over segments or returning (segments, info)
    result = model.transcribe(str(src), beam_size=5, word_timestamps=True)
    if isinstance(result, tuple) and len(result) == 2:
        segment_iter = result[0]
    else:
        segment_iter = result

    for segment in segment_iter:
        # segment may be a dict-like object or a simple object with attributes
        if isinstance(segment, dict):
            start = segment.get("start")
            end = segment.get("end")
            text = segment.get("text", "")
            word_items = segment.get("words", [])
        else:
            start = getattr(segment, "start", None)
            end = getattr(segment, "end", None)
            text = getattr(segment, "text", "")
            word_items = getattr(segment, "words", [])

        if hasattr(word_items, "__iter__") and not isinstance(word_items, (str, bytes, dict)):
            word_items = list(word_items)

        seg = {
            "start": float(start or 0.0),
            "end": float(end or 0.0),
            "text": text,
            "words": [],
        }
        for w in word_items:
            if isinstance(w, dict):
                ws = float(w.get("start", 0.0))
                we = float(w.get("end", ws))
                wt = w.get("text", "")
                wc = w.get("confidence", None)
            else:
                ws = float(getattr(w, "start", 0.0))
                we = float(getattr(w, "end", ws))
                wt = getattr(w, "word", "")
                wc = getattr(w, "confidence", None)
            word = {"start": ws, "end": we, "text": wt, "confidence": wc}
            seg["words"].append(word)
            words_all.append(word)
        segments.append(seg)

    transcript: Dict = {
        "source": str(src),
        "model": model_size,
        "duration": _ffprobe_duration(src),
        "segments": segments,
        "words": words_all,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    return str(out_path)

