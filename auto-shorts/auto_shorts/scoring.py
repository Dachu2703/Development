from typing import List, Dict, Tuple, Optional
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

MAX_SHORT_DURATION = 180


def duration_bounds(target_duration: int) -> Tuple[int, int]:
    """Return the preferred duration range for a requested Short.

    The upper bound is deliberately a little flexible for a natural sentence
    boundary, but is never allowed to exceed the product-wide three minute
    limit.
    """
    target = int(target_duration)
    if not 1 <= target <= MAX_SHORT_DURATION:
        raise ValueError(f"target_duration must be between 1 and {MAX_SHORT_DURATION} seconds")
    return max(5, int(target * 0.85)), min(MAX_SHORT_DURATION, max(target, int(target * 1.15)))


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


def _peak_centered_window(segments: List[Dict], peak_index: int, target: float, maximum: float) -> Tuple[float, float]:
    """Build a context window around a scored transcript segment.

    Transcript segment boundaries are used whenever possible, expanding before
    and after the peak instead of starting a clip at the peak itself.
    """
    peak = segments[peak_index]
    start = float(peak.get("start", 0.0))
    end = float(peak.get("end", start))
    peak_start, peak_end = start, end
    left, right = peak_index - 1, peak_index + 1

    while (left >= 0 or right < len(segments)) and end - start < target:
        left_length = (end - float(segments[left].get("start", start))) if left >= 0 else float("inf")
        right_length = (float(segments[right].get("end", end)) - start) if right < len(segments) else float("inf")
        # Add the side that stays closest to the target, while respecting max.
        choices = []
        if left >= 0 and left_length <= maximum:
            proposed_start = float(segments[left].get("start", start))
            context_imbalance = abs((peak_start - proposed_start) - (end - peak_end))
            choices.append((context_imbalance, abs(target - left_length), "left"))
        if right < len(segments) and right_length <= maximum:
            proposed_end = float(segments[right].get("end", end))
            context_imbalance = abs((peak_start - start) - (proposed_end - peak_end))
            choices.append((context_imbalance, abs(target - right_length), "right"))
        if not choices:
            break
        side = min(choices)[2]
        if side == "left":
            start = float(segments[left].get("start", start))
            left -= 1
        else:
            end = float(segments[right].get("end", end))
            right += 1

    # A transcript segment may itself exceed the cap. Keep the peak within a
    # capped window; later alignment can still move it to a nearby pause.
    if end - start > maximum:
        midpoint = (float(peak.get("start", start)) + float(peak.get("end", end))) / 2
        start = max(start, midpoint - maximum / 2)
        end = start + maximum
    return start, end


def score_sentences(transcript_path: str, min_length: int = 15, max_length: int = 60, top_k: int = 5, prioritize_length: bool = False, force_exact_length: bool = False, exact_clip_length: int | None = None, target_duration: Optional[int] = None) -> List[Dict]:
    """Score sentences/segments from a transcript JSON and return top candidate clips.

    Transcript JSON should contain `segments` (with start,end,text) or `words`.
    The function returns a list of dicts: {start, end, score, reason}
    """
    with open(transcript_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    segments = data.get("segments") or []
    words = data.get("words") or []
    if not segments and words:
        # Aggregate words into rough segments sized around desired top_k candidates
        segments = []
        if not words:
            return []
        # Create segments based on duration. If prioritize_length is set, use max_length windows;
        # otherwise use duration/top_k and clamp to [min_length, max_length].
        dur = data.get("duration", 0)
        if not dur:
            return []
        if prioritize_length:
            if force_exact_length and exact_clip_length:
                # use exact fixed windows of exact_clip_length seconds
                step = int(max(1, exact_clip_length))
            else:
                step = min(max_length, max(min_length, max_length))
        else:
            # ideal step is dur/top_k, but clamp to [min_length, max_length]
            if top_k <= 0:
                return []
            ideal = dur / max(1, top_k)
            step = min(max_length, max(min_length, ideal))
        t = 0.0
        while t < dur:
            segments.append({"start": t, "end": min(t + step, dur), "text": ""})
            t += step

    if target_duration is not None:
        min_length, max_length = duration_bounds(target_duration)
    max_length = min(int(max_length), MAX_SHORT_DURATION)

    candidates: List[Dict] = []
    for index, seg in enumerate(segments):
        peak_start = float(seg.get("start", 0.0))
        peak_end = float(seg.get("end", peak_start))
        start = peak_start
        end = peak_end
        text = seg.get("text", "")
        if target_duration is not None:
            start, end = _peak_centered_window(segments, index, float(target_duration), float(max_length))
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
        if target_duration is not None:
            reason_parts.append("peak-centered")
            # A complete Short should present the statement with some setup
            # and a follow-through, not begin or end at the peak itself.
            if start < peak_start and end > peak_end:
                reason_parts.append("context-before-after")
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

    # Rank by engagement to decide *which* unique moments to keep, then return
    # them in source order. Export therefore follows the original narrative
    # rather than jumping between timestamps by descending score.
    return sorted(picks, key=lambda clip: (clip["start"], clip["end"]))


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

