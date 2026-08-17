"""Main-content camera transition detection.

This module integrates with the existing auto-shorts pipeline. After
``scoring.py`` and ``align.py`` select the clips to export, these helpers find
the candidate points *inside* each clip where the main speaker moves into
"main content" — topic changes, important statements, numbers, and so on.

The functions here only produce **metadata** (timing + type + duration). The
actual ffmpeg work happens in :mod:`auto_shorts.export`, which consumes the
annotated ``transitions`` list without ever modifying the clip start/end.
That guarantees the transition layer can never remove, shorten, or skip the
main speaker's content — it only adds a smooth visual emphasis around it.
"""

from typing import Dict, List, Optional

TRANSITION_TYPES = ("zoom_in", "zoom_out", "fade_through")

DEFAULT_TRANSITIONS_CONFIG: Dict = {
    "enabled": False,
    "type": "zoom_in",        # zoom_in | zoom_out | fade_through
    "duration": 1.6,          # seconds that the transition effect takes
    "min_gap": 6.0,           # minimum seconds between two transitions
    "threshold": 3.0,         # content importance score that triggers one
    "max_per_clip": 3,        # hard cap on transitions within one short
    "peak_zoom": 1.08,        # nominal zoom applied for zoom_in/zoom_out
    "max_zoom": 1.12,         # absolute upper zoom, keeps face readable
}

# A transition may consume at most this fraction of a clip's duration so the
# actual statement always stays fully visible and audible.
MAX_TRANSITION_FRACTION = 0.25


# --------------------------------------------------------------------------
# Main-content detection
# --------------------------------------------------------------------------
def _content_score(text: str) -> float:
    """Reuse the existing scoring heuristics used by the short-selection step.

    The transition logic therefore agrees with ``scoring.py`` about what is
    really the "main" content rather than inventing a second definition.
    """
    from .scoring import _keyword_score, _number_score, _question_score

    return float(_keyword_score(text) + _number_score(text) + _question_score(text))


def detect_main_content_points(
    clip: Dict,
    transcript_segments: List[Dict],
    threshold: float = 3.0,
) -> List[Dict]:
    """Return the sub-intervals of ``clip`` that qualify as main content.

    ``transcript_segments`` are the Whisper sentence-level boundaries already
    produced by the pipeline.  Each returned dict contains ``start``, ``end``,
    ``text`` and the score that made it qualify.
    """
    clip_start = float(clip.get("start", 0.0))
    clip_end = float(clip.get("end", clip_start))
    points: List[Dict] = []

    for seg in transcript_segments or []:
        seg_start = float(seg.get("start", 0.0))
        seg_end = float(seg.get("end", seg_start))
        if seg_end <= clip_start or seg_start >= clip_end:
            continue
        text = str(seg.get("text", ""))
        score = _content_score(text)
        if score >= threshold:
            points.append(
                {
                    "start": max(seg_start, clip_start),
                    "end": min(seg_end, clip_end),
                    "text": text,
                    "score": score,
                }
            )
    return points


# --------------------------------------------------------------------------
# Transition placement
# --------------------------------------------------------------------------
def find_transition_points(
    clip: Dict,
    points: List[Dict],
    config: Dict,
) -> List[Dict]:
    """Map main-content points to natural transition offsets.

    Rules used:

    * a transition is placed at the **start** of every important statement
      so the visual change introduces the topic without covering it;
    * the first transition snaps to the very beginning of the clip when the
      first important statement lands within ``min_gap`` seconds of it;
    * transitions are never closer together than ``min_gap`` seconds;
    * no more than ``max_per_clip`` transitions are emitted;
    * a transition is skipped if there is not enough room left in the clip
      for its full duration (prevents an effect being cut mid-pulse).

    The returned offsets are relative 0..1 positions inside the clip so they
    remain valid after any future re-cropping step.
    """
    clip_start = float(clip.get("start", 0.0))
    clip_end = float(clip.get("end", clip_start))
    length = clip_end - clip_start
    if length <= 0.0:
        return []

    kind = str(config.get("type", "zoom_in"))
    if kind not in TRANSITION_TYPES:
        kind = "zoom_in"
    duration = min(
        float(config.get("duration", DEFAULT_TRANSITIONS_CONFIG["duration"])),
        length * MAX_TRANSITION_FRACTION,
    )
    min_gap = float(config.get("min_gap", DEFAULT_TRANSITIONS_CONFIG["min_gap"]))
    max_per_clip = int(config.get("max_per_clip", DEFAULT_TRANSITIONS_CONFIG["max_per_clip"]))

    # Natural slots = starts of the important sub-statements.
    candidates = sorted(float(p["start"]) for p in (points or []))
    if candidates and (candidates[0] - clip_start) <= min_gap:
        candidates[0] = clip_start

    out: List[Dict] = []
    last_ts = -1e9
    for t in candidates:
        # leave enough room for the full effect before the clip end
        if t > clip_end - duration:
            continue
        if (t - last_ts) < min_gap:
            continue

        out.append(
            {
                "offset": round((t - clip_start) / length, 4),
                "type": kind,
                "duration": round(duration, 3),
            }
        )
        last_ts = t
        if len(out) >= max_per_clip:
            break
    return out


def apply_transitions(
    aligned_clips: List[Dict],
    transcript_data: Optional[Dict],
    config: Optional[Dict],
) -> List[Dict]:
    """Annotate every aligned clip with a ``transitions`` list.

    When transitions are disabled, the field is removed altogether so the
    manifest stays clean and the export layer receives a clear signal that
    no transition work is needed.
    """
    if not config or not config.get("enabled"):
        for seg in aligned_clips or []:
            seg.pop("transitions", None)
        return aligned_clips or []

    transcript_segments = (transcript_data or {}).get("segments", []) or []
    threshold = float(config.get("threshold", DEFAULT_TRANSITIONS_CONFIG["threshold"]))

    for seg in aligned_clips or []:
        points = detect_main_content_points(seg, transcript_segments, threshold)
        seg["transitions"] = find_transition_points(seg, points, config)

    return aligned_clips or []