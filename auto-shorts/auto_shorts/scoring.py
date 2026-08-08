from typing import List, Dict, Tuple
import json
import re


KEYWORDS = [
    "key point",
    "important",
    "biggest",
    "mistake",
    "remember",
    "tip",
    "note",
    "question",
    "don't",
    "do not",
]


def _keyword_score(text: str) -> float:
    t = text.lower()
    score = 0.0
    for k in KEYWORDS:
        if k in t:
            score += 3.0
    return score


def _number_score(text: str) -> float:
    if re.search(r"\d+|%", text):
        return 1.5
    return 0.0


def _question_score(text: str) -> float:
    return 1.5 if text.strip().endswith("?") else 0.0


def _length_score(length: float, min_length: int, max_length: int) -> float:
    # prefer lengths in the middle of min/max
    if length < min_length:
        return -1.0
    if length > max_length:
        # penalize but allow
        return max(0.0, 1.0 - (length - max_length) / max_length)
    # normalized to [0,1]
    mid = (min_length + max_length) / 2.0
    return 1.0 - abs(length - mid) / (max_length - min_length + 1e-6)


def _overlaps(a: Tuple[float, float], b: Tuple[float, float], buffer: float = 5.0) -> bool:
    # consider overlapping if within buffer seconds
    return not (a[1] + buffer < b[0] or b[1] + buffer < a[0])


def score_sentences(transcript_path: str, min_length: int = 15, max_length: int = 60, top_k: int = 5) -> List[Dict]:
    """Score sentences/segments from a transcript JSON and return top candidate clips.

    Transcript JSON should contain `segments` (with start,end,text) or `words`.
    The function returns a list of dicts: {start, end, score, reason}
    """
    with open(transcript_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    segments = data.get("segments") or []
    if not segments and data.get("words"):
        # Aggregate words into rough segments of 10s windows
        words = data["words"]
        segments = []
        if not words:
            return []
        # Create small segments around every 10s window
        dur = data.get("duration", 0)
        step = min(max_length, max(10, dur / 10 if dur else 10))
        t = 0.0
        while t < dur:
            segments.append({"start": t, "end": min(t + step, dur), "text": ""})
            t += step

    candidates: List[Dict] = []
    for seg in segments:
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        text = seg.get("text", "")
        length = end - start
        ks = _keyword_score(text)
        ns = _number_score(text)
        qs = _question_score(text)
        ls = _length_score(length, min_length, max_length)
        total = ks * 1.0 + ns * 1.0 + qs * 1.0 + ls * 1.0
        reason_parts = []
        if ks > 0:
            reason_parts.append("keywords")
        if ns > 0:
            reason_parts.append("numbers")
        if qs > 0:
            reason_parts.append("question")
        reason_parts.append(f"len={int(length)}")
        candidates.append({"start": start, "end": end, "score": float(total), "reason": ",".join(reason_parts)})

    # sort by score desc
    candidates = sorted(candidates, key=lambda x: x["score"], reverse=True)

    # pick top_k non-overlapping
    picks: List[Dict] = []
    for c in candidates:
        interval = (c["start"], c["end"])
        conflict = False
        for p in picks:
            if _overlaps(interval, (p["start"], p["end"])):
                conflict = True
                break
        if not conflict:
            picks.append(c)
        if len(picks) >= top_k:
            break

    return picks


def ensure_no_midword(clips: List[Dict], transcript_path: str, eps: float = 0.02) -> bool:
    """Validate that no clip start/end cuts through a word.

    Returns True if all clip boundaries fall outside word interiors (or align to starts/ends).
    """
    with open(transcript_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    words = data.get("words", [])
    intervals = [(w["start"], w["end"]) for w in words if "start" in w and "end" in w]

    for clip in clips:
        for boundary in (clip["start"], clip["end"]):
            for wstart, wend in intervals:
                # if boundary is strictly inside a word interval (with epsilon), it's a mid-word cut
                if (wstart + eps) < boundary < (wend - eps):
                    return False
    return True

