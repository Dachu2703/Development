import hashlib
import json
import subprocess
from pathlib import Path
from typing import Dict, List


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
        print(f"[auto-shorts] faster-whisper using compute_type={compute_type} device=cpu model={model_size}")
    except Exception:
        compute_type = "default"
        model = WhisperModel(model_size, device="cpu")
        print(f"[auto-shorts] faster-whisper fallback to compute_type={compute_type} device=cpu model={model_size}")

    segments = []
    words_all: List[Dict] = []
    # faster-whisper allows streaming over segments
    for segment in model.transcribe(str(src), beam_size=5, word_timestamps=True):
        # segment is a dict-like object with start/end/text/words
        seg = {
            "start": float(segment.start),
            "end": float(segment.end),
            "text": segment.text,
            "words": [],
        }
        if hasattr(segment, "words") and segment.words:
            for w in segment.words:
                word = {"start": float(w.start), "end": float(w.end), "text": w.word, "confidence": getattr(w, "confidence", None)}
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

