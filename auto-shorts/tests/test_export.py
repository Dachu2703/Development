from pathlib import Path

from auto_shorts.export import (
    _build_bottom_image_filter,
    _build_image_fit_filter,
    _build_reference_template_filter,
    _build_shrink_to_frame_filter,
    _build_single_frame_filter,
    _build_three_band_filter,
    _compute_three_section_heights,
    _get_ffmpeg_preset,
    _should_use_three_part_layout,
    _verify_video_file,
    export_clips,
)


def test_ffmpeg_preset_uses_nvenc_compatible_values():
    assert _get_ffmpeg_preset("hevc_nvenc", True) == "p1"
    assert _get_ffmpeg_preset("hevc_nvenc", False) == "p4"
    assert _get_ffmpeg_preset("libx264", True) == "ultrafast"
    assert _get_ffmpeg_preset("libx264", False) == "veryfast"


def test_video_without_audio_is_still_valid_for_verification(tmp_path):
    src = tmp_path / "video_no_audio.mp4"

    import subprocess

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=1280x720:rate=30:duration=1",
            "-pix_fmt",
            "yuv420p",
            str(src),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert _verify_video_file(src, 1280, 720) == []


def test_image_fit_filter_uses_cover_scaling_and_bottom_crop():
    image_filter = _build_image_fit_filter(
        "[1:v]",
        "[image]",
        1080,
        480,
    )

    assert "ceil(max(1080,iw*480/ih)/2)*2" in image_filter
    assert "ceil(max(480,ih*1080/iw)/2)*2" in image_filter
    assert "crop=1080:480:x='(iw-ow)/2':y='ih-oh'[image]" in image_filter


def test_three_band_banner_labels_drawtext_output():
    image_filter = _build_three_band_filter(
        1080,
        1920,
        {"title": "Topic", "name": "Guest"},
        10.0,
    )

    assert "y=(h-text_h)/2[banner]" in image_filter
    assert "d=10[banner],drawtext" not in image_filter


def test_three_band_filter_uses_selected_output_dimensions():
    out_w = 1080
    out_h = 1920

    image_filter = _build_three_band_filter(
        out_w,
        out_h,
        None,
        10.0,
    )

    assert f"color=c=0x101522:s={out_w}x288" in image_filter

    assert (
        f"scale={out_w}:576:force_original_aspect_ratio=disable,"
        f"setsar=1[bottom_image]"
    ) in image_filter


def test_bottom_image_is_scaled_to_exact_panel_rectangle():
    out_w = 1080
    out_h = 480

    image_filter = _build_bottom_image_filter(
        "[1:v]",
        "[bottom]",
        out_w,
        out_h,
    )

    assert image_filter == (
        f"[1:v]scale={out_w}:{out_h}:"
        f"force_original_aspect_ratio=disable,"
        f"setsar=1[bottom]"
    )


def test_reference_template_bottom_image_is_composited_into_panel():
    out_w = 1080
    out_h = 1920

    image_filter = _build_reference_template_filter(
        out_w,
        out_h,
        {
            "top_height": 180,
            "video_height": 900,
            "title_height": 300,
            "subscribe_height": 220,
            "bottom_background": "white_blue",
        },
        10.0,
        has_bottom_image=True,
    )

    assert (
        f"scale={out_w}:320:"
        f"force_original_aspect_ratio=disable,"
        f"setsar=1[bottom_image]"
    ) in image_filter

    assert "[bottom_bg][bottom_image]overlay" in image_filter


def test_three_section_layout_defaults_to_55_15_30():
    out_h = 1920

    layout = _compute_three_section_heights(out_h)

    assert layout == {
        "video": 1056,
        "title": 288,
        "image": 576,
    }

    assert sum(layout.values()) == out_h


def test_three_section_layout_scales_for_720p_short():
    out_h = 1280

    layout = _compute_three_section_heights(out_h)

    assert layout == {
        "video": 704,
        "title": 192,
        "image": 384,
    }

    assert sum(layout.values()) == out_h


def test_vertical_shorts_fill_selected_frame_with_crop():
    # These values simulate one possible UI selection.
    out_w = 1080
    out_h = 1920

    filter_text = _build_shrink_to_frame_filter(
        1920,
        1080,
        out_w,
        out_h,
    )

    assert "force_original_aspect_ratio=increase" in filter_text
    assert f"crop={out_w}:{out_h}" in filter_text
    assert "pad=" not in filter_text


def test_single_frame_layout_defaults_to_single_when_no_title_or_image():
    assert (
        _should_use_three_part_layout(
            "single",
            None,
            None,
            {},
        )
        is False
    )

    assert (
        _should_use_three_part_layout(
            "auto",
            None,
            None,
            {},
        )
        is False
    )

    assert (
        _should_use_three_part_layout(
            "three_part",
            None,
            None,
            {"title": "Topic"},
        )
        is True
    )


def test_single_frame_selection_is_a_strict_override_even_with_title_or_image():
    assert (
        _should_use_three_part_layout(
            "Single Frame",
            "Topic",
            "image.png",
            {"title": "Guest"},
        )
        is False
    )

    assert (
        _should_use_three_part_layout(
            "single_frame",
            "Topic",
            "image.png",
            {"title": "Guest"},
        )
        is False
    )

    assert (
        _should_use_three_part_layout(
            "Full Size Short Video",
            "Topic",
            "image.png",
            {"title": "Guest"},
        )
        is False
    )

    assert (
        _should_use_three_part_layout(
            "full_size_short_video",
            "Topic",
            "image.png",
            {"title": "Guest"},
        )
        is False
    )


def test_three_part_selection_is_a_strict_override_even_without_title_or_image():
    assert (
        _should_use_three_part_layout(
            "3-Part Frame",
            None,
            None,
            {},
        )
        is True
    )

    assert (
        _should_use_three_part_layout(
            "three_part_frame",
            None,
            None,
            {},
        )
        is True
    )


def test_three_part_layout_skips_missing_bottom_image_input(
    monkeypatch,
    tmp_path,
):
    from types import SimpleNamespace

    captured = {}

    def fake_run(cmd, capture_output, text):
        out_path = Path(cmd[-1])

        out_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        out_path.write_bytes(b"fake video")

        captured["cmd"] = cmd

        return SimpleNamespace(
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        "auto_shorts.export.subprocess.run",
        fake_run,
    )

    monkeypatch.setattr(
        "auto_shorts.export._verify_video_file",
        lambda *args, **kwargs: [],
    )

    export_clips(
        "dummy.mp4",
        [{"start": 0.0, "end": 1.0}],
        str(tmp_path),
        bottom_image_path=None,
        frame_layout="3-Part Frame",
    )

    assert "None" not in captured["cmd"]

    assert (
        "-loop" not in captured["cmd"]
        or captured["cmd"].count("-loop") == 0
    )


def test_single_frame_filter_fills_selected_frame_with_crop():
    # These values simulate one possible UI selection.
    out_w = 1080
    out_h = 1920

    filter_text = _build_single_frame_filter(
        1920,
        1080,
        out_w,
        out_h,
    )

    assert "force_original_aspect_ratio=increase" in filter_text
    assert f"crop={out_w}:{out_h}" in filter_text
    assert "pad=" not in filter_text