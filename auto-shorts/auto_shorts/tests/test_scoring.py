import json
from pathlib import Path

from auto_shorts.scoring import ensure_no_midword, score_sentences


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
