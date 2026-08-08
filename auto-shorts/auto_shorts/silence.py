import subprocess
from typing import List, Tuple


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


def detect_silences(video_path: str, noise_db: int = -30, min_silence_len: float = 0.5) -> List[Tuple[float, float]]:
    """Detect silences using ffmpeg's silencedetect filter, falling back to pydub.

    Returns a list of (start, end) silence intervals in seconds.
    """
    # Try ffmpeg first
    silences = _ffmpeg_silence_detect(video_path, noise_db=noise_db, min_silence_len=min_silence_len)
    if silences:
        return silences
    # Fallback to pydub
    return _pydub_detect(video_path, noise_db=noise_db, min_silence_len=min_silence_len)

