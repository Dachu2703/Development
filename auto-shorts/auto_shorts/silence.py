import subprocess
import hashlib
import json
from pathlib import Path
from typing import List, Tuple


DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[1] / ".auto_shorts_cache"


def _silence_cache_path(video_path: str, noise_db: int, min_silence_len: float, cache_dir: str | None) -> Path:
    source = Path(video_path)
    stat = source.stat()
    key = f"{source.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|{noise_db}|{min_silence_len}"
    directory = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{source.stem}-{hashlib.sha1(key.encode()).hexdigest()}.silences.json"


def _ffmpeg_silence_detect(video_path: str, noise_db: int = -30, min_silence_len: float = 0.5) -> List[Tuple[float, float]]:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        video_path,
        "-af",
        f"silencedetect=noise={noise_db}dB:d={min_silence_len}",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return []
    out = proc.stderr.splitlines()
    silences = []
    current_start = None
    for line in out:
        line = line.strip()
        if "silence_start:" in line:
            try:
                current_start = float(line.split("silence_start:")[-1].strip())
            except Exception:
                current_start = None
        if "silence_end:" in line:
            try:
                parts = line.split("silence_end:")[-1].strip().split("|")
                end = float(parts[0].strip())
                if current_start is None:
                    start = 0.0
                else:
                    start = current_start
                silences.append((start, end))
            except Exception:
                continue
            current_start = None
    return silences


def _pydub_detect(video_path: str, noise_db: int = -30, min_silence_len: float = 0.5) -> List[Tuple[float, float]]:
    try:
        from pydub import AudioSegment, silence as pydub_silence
    except Exception:
        return []
    try:
        audio = AudioSegment.from_file(video_path)
    except Exception:
        return []
    # pydub uses ms
    min_silence_ms = int(min_silence_len * 1000)
    silence_thresh = noise_db
    intervals = pydub_silence.detect_silence(audio, min_silence_len=min_silence_ms, silence_thresh=silence_thresh)
    # convert to seconds and normalize tuples
    return [(float(start_ms / 1000.0), float(end_ms / 1000.0)) for start_ms, end_ms in intervals]


def detect_silences(video_path: str, noise_db: int = -30, min_silence_len: float = 0.5, cache_dir: str | None = None) -> List[Tuple[float, float]]:
    """Detect silences using ffmpeg's silencedetect filter, falling back to pydub.

    Returns a list of (start, end) silence intervals in seconds.
    """
    cache_path = _silence_cache_path(video_path, noise_db, min_silence_len, cache_dir)
    if cache_path.exists():
        try:
            return [(float(start), float(end)) for start, end in json.loads(cache_path.read_text(encoding="utf-8"))]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # Ignore a partial/corrupt cache and regenerate it.
            pass

    # Try ffmpeg first
    silences = _ffmpeg_silence_detect(video_path, noise_db=noise_db, min_silence_len=min_silence_len)
    if silences:
        result = silences
    else:
        # Fallback to pydub
        result = _pydub_detect(video_path, noise_db=noise_db, min_silence_len=min_silence_len)
    cache_path.write_text(json.dumps(result), encoding="utf-8")
    return result

