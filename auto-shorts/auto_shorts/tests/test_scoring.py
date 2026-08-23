import json
from pathlib import Path

import pytest

from auto_shorts.scoring import MAX_SHORT_DURATION, duration_bounds, ensure_no_midword, score_sentences


def test_ensure_no_midword_ok(tmp_path: Path):
    # build a fake transcript with words
    transcript = {
        "source": "input.mp4",
        "duration": 30.0,
        "words": [
            {"start": 0.0, "end": 0.5, "text": "Hello"},
            {"start": 0.6, "end": 1.0, "text": "world"},
            {"start": 5.0, "end": 5.5, "text": "key"},
            {"start": 5.6, "end": 6.0, "text": "point"},
        ],
    }
    path = tmp_path / "transcript.json"
    path.write_text(json.dumps(transcript))

    clips = [{"start": 0.5, "end": 1.0}, {"start": 5.5, "end": 6.0}]
    assert ensure_no_midword(clips, str(path))


def test_ensure_no_midword_fail(tmp_path: Path):
    transcript = {
        "source": "input.mp4",
        "duration": 30.0,
        "words": [
            {"start": 0.0, "end": 0.5, "text": "Hello"},
            {"start": 0.6, "end": 1.0, "text": "world"},
        ],
    }
    path = tmp_path / "transcript.json"
    path.write_text(json.dumps(transcript))

    # clip starts inside word 'world' (0.6-1.0)
    clips = [{"start": 0.7, "end": 1.5}]
    assert not ensure_no_midword(clips, str(path))


def test_score_sentences_basic(tmp_path: Path):
    transcript = {
        "source": "input.mp4",
        "duration": 120.0,
        "segments": [
            {"start": 0.0, "end": 20.0, "text": "This is an introduction."},
            {"start": 20.0, "end": 40.0, "text": "The key point is that 50% of users..."},
            {"start": 40.0, "end": 70.0, "text": "Some filler content."},
        ],
    }
    path = tmp_path / "transcript2.json"
    path.write_text(json.dumps(transcript))
    picks = score_sentences(str(path), min_length=15, max_length=60, top_k=2)
    # should pick the segment with 'key point' as top
    assert len(picks) >= 1
    assert any("keywords" in p.get("reason", "") or "numbers" in p.get("reason", "") for p in picks)


def test_target_duration_builds_a_peak_centered_clip(tmp_path: Path):
    transcript = {
        "duration": 120.0,
        "segments": [
            {"start": 0, "end": 20, "text": "introductory context"},
            {"start": 20, "end": 40, "text": "more context before the answer"},
            {"start": 40, "end": 60, "text": "The key point is 50% of users make this mistake."},
            {"start": 60, "end": 80, "text": "the explanation and conclusion"},
            {"start": 80, "end": 100, "text": "unrelated closing remarks"},
        ],
    }
    path = tmp_path / "peaks.json"
    path.write_text(json.dumps(transcript))

    picks = score_sentences(str(path), target_duration=60, top_k=1)

    assert len(picks) == 1
    clip = picks[0]
    assert clip["start"] < 40 < clip["end"]
    assert clip["end"] - clip["start"] <= 69
    assert "peak-centered" in clip["reason"]


def test_target_duration_prefers_key_point_with_follow_through(tmp_path: Path):
    transcript = {
        "duration": 100.0,
        "segments": [
            {"start": 10, "end": 30, "text": "The key point is to prepare first."},
            {"start": 30, "end": 50, "text": "This is a separate topic."},
            {"start": 50, "end": 65, "text": "The important result is 80%."},
            {"start": 65, "end": 80, "text": "Therefore, you should apply this every time."},
        ],
    }
    path = tmp_path / "sequence.json"
    path.write_text(json.dumps(transcript))

    picks = score_sentences(str(path), target_duration=40, top_k=1)

    assert len(picks) == 1
    assert "follow-through" in picks[0]["reason"]


def test_duration_bounds_enforces_three_minute_limit():
    assert duration_bounds(MAX_SHORT_DURATION) == (153, MAX_SHORT_DURATION)
    with pytest.raises(ValueError):
        duration_bounds(MAX_SHORT_DURATION + 1)


def test_selected_highlights_are_returned_in_source_order(tmp_path: Path):
    transcript = {
        "duration": 140.0,
        "segments": [
            {"start": 0, "end": 20, "text": "A key point for the audience."},
            {"start": 20, "end": 40, "text": "ordinary explanation"},
            {"start": 100, "end": 120, "text": "The biggest tip is a surprising 50% result."},
        ],
    }
    path = tmp_path / "ordered.json"
    path.write_text(json.dumps(transcript))

    picks = score_sentences(str(path), min_length=15, max_length=60, top_k=2)

    assert len(picks) == 2
    assert [clip["start"] for clip in picks] == sorted(clip["start"] for clip in picks)


def test_intro_segments_are_excluded_from_top_candidates(tmp_path: Path):
    transcript = {
        "duration": 80.0,
        "segments": [
            {"start": 0, "end": 15, "text": "This is an introduction to the video."},
            {"start": 15, "end": 35, "text": "The key point is that the process saves 50% time."},
            {"start": 35, "end": 55, "text": "Important tip: focus on the main action."},
        ],
    }
    path = tmp_path / "intro_exclusion.json"
    path.write_text(json.dumps(transcript))

    picks = score_sentences(str(path), min_length=15, max_length=60, top_k=2)

    assert len(picks) >= 1
    assert all(clip["start"] >= 15 for clip in picks)


def test_generic_opening_preamble_is_excluded_before_content(tmp_path: Path):
    transcript = {
        "duration": 120.0,
        "segments": [
            {"start": 0, "end": 12, "text": "We are going to talk about the feature today."},
            {"start": 12, "end": 30, "text": "The big mistake is to skip the setup step."},
            {"start": 30, "end": 50, "text": "Remember: the key point is to focus on the final result."},
        ],
    }
    path = tmp_path / "generic_intro.json"
    path.write_text(json.dumps(transcript))

    picks = score_sentences(str(path), min_length=15, max_length=60, top_k=2)

    assert len(picks) >= 1
    assert all(clip["start"] >= 12 for clip in picks)


def test_first_ten_seconds_are_never_selected(tmp_path: Path):
    transcript = {
        "duration": 60.0,
        "segments": [
            {"start": 0, "end": 6, "text": "Opening music and welcome."},
            {"start": 6, "end": 12, "text": "Opening context."},
            {"start": 12, "end": 30, "text": "The important solution is to act early."},
        ],
    }
    path = tmp_path / "first_ten_seconds.json"
    path.write_text(json.dumps(transcript))

    picks = score_sentences(str(path), min_length=5, max_length=60, top_k=3, target_duration=20)

    assert picks
    assert all(clip["start"] >= 10 for clip in picks)
