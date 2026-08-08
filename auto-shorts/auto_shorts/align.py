from typing import List, Tuple, Dict, Optional
import json


def _find_prev_silence_end(silence_ends: List[float], t: float) -> float:
    prev = 0.0
    for se in silence_ends:
        if se <= t:
            prev = se
        else:
            break
    return prev


def _find_next_silence_start(silence_starts: List[float], t: float, default: float) -> float:
    for ss in silence_starts:
        if ss >= t:
            return ss
    return default


def _snap_to_word_boundary(boundary: float, words: List[Dict], side: str = "start") -> float:
    # if boundary falls inside a word, move to nearest boundary depending on side
    for w in words:
        ws = w.get("start")
        we = w.get("end")
        if ws is None or we is None:
            continue
        if ws <= boundary <= we:
            return ws if side == "start" else we
    return boundary


def snap_to_silence(
    candidates: List[Dict],
    silences: List[Tuple[float, float]],
    transcript_path: Optional[str] = None,
    min_length: int = 15,
    max_length: int = 60,
) -> List[Dict]:
    """Snap candidate segments to nearest silence boundaries and adjust to word boundaries.

    If `transcript_path` is provided and contains `words`, clip boundaries that fall inside a word
    will be adjusted outward to the word start/end to avoid mid-word cuts.
    """
    silence_starts = [s for s, _ in silences]
    silence_ends = [e for _, e in silences]
    silence_starts.sort()
    silence_ends.sort()

    words = []
    duration = None
    if transcript_path:
        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            words = data.get("words", [])
            duration = data.get("duration")
        except Exception:
            words = []

    out = []
    for c in candidates:
        s = float(c.get("start", 0.0))
        e = float(c.get("end", s))

        # snap to nearest silence boundaries: start -> previous silence end, end -> next silence start
        new_start = _find_prev_silence_end(silence_ends, s) if silence_ends else max(0.0, s)
        new_end = _find_next_silence_start(silence_starts, e, e) if silence_starts else e

        # if transcript words available, avoid cutting mid-word
        if words:
            new_start = _snap_to_word_boundary(new_start, words, side="start")
            new_end = _snap_to_word_boundary(new_end, words, side="end")

        # enforce min/max
        if new_end - new_start < min_length:
            new_end = new_start + min_length
        if new_end - new_start > max_length:
            new_end = new_start + max_length

        # clamp to duration if available
        if duration is not None:
            if new_end > duration:
                new_end = duration
            if new_start < 0:
                new_start = 0.0

        out.append({"start": max(0.0, new_start), "end": float(new_end), **{k: v for k, v in c.items() if k not in ("start", "end")}})

    return out

