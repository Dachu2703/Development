"""Tests for the main-content camera transition module."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_shorts import transitions


@pytest.fixture
def transcript():
    return {
        "source": "fake.mp4",
        "duration": 120.0,
        "segments": [
            {"start": 0.0, "end": 5.0, "text": "Hello everyone and welcome back."},
            {"start": 5.2, "end": 9.0, "text": "Today I want to share the most important tip."},
            {"start": 9.2, "end": 14.0, "text": "Remember to subscribe."},
        ],
        "words": [],
    }


def make_config(**overrides):
    cfg = dict(transitions.DEFAULT_TRANSITIONS_CONFIG)
    cfg.update(overrides)
    return cfg


def test_detect_main_content_points(transcript):
    points = transitions.detect_main_content_points(
        {"start": 0.0, "end": 15.0}, transcript["segments"], threshold=3.0
    )
    # Both "most important tip" (score 6) and "Remember" (score 3) qualify
    assert len(points) == 2
    assert points[0]["start"] == pytest.approx(5.2)
    assert points[0]["score"] == pytest.approx(6.0)
    assert points[1]["start"] == pytest.approx(9.2)


def test_transitions_never_change_clip_bounds(transcript):
    config = make_config(enabled=True, type="zoom_in", duration=1.6, min_gap=2.0)
    seg = {"start": 0.0, "end": 15.0, "reason": "test"}
    before = (seg["start"], seg["end"])
    result = transitions.apply_transitions([dict(seg)], transcript, config)
    assert result[0]["start"] == before[0]
    assert result[0]["end"] == before[1]


def test_transitions_disabled_removes_metadata(transcript):
    seg = {"start": 0.0, "end": 15.0, "reason": "test", "transitions": [{"offset": 0.2}]}
    result = transitions.apply_transitions([seg], transcript, make_config(enabled=False))
    assert "transitions" not in result[0]


def test_max_transitions_per_clip(transcript):
    config = make_config(enabled=True, type="zoom_in", duration=1.0, min_gap=0.1, max_per_clip=1)
    seg = {"start": 0.0, "end": 60.0, "reason": "test"}
    result = transitions.apply_transitions([seg], transcript, config)
    assert len(result[0].get("transitions", [])) <= 1


def test_duration_capped_by_clip():
    seg = {"start": 0.0, "end": 10.0, "reason": "test"}
    pts = [{"start": 2.0, "end": 4.0, "text": "important", "score": 4.0}]
    trans = transitions.find_transition_points(seg, pts, make_config(duration=5.0))
    if trans:
        assert trans[0]["duration"] <= 10.0 * transitions.MAX_TRANSITION_FRACTION