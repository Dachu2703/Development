from auto_shorts.export import _build_guest_overlay, _build_image_fit_filter, _build_reference_template_filter, _build_three_band_filter, _compute_crop_x, _compute_crop_y, export_clips, _find_font_file
from auto_shorts import runner


def test_compute_crop_center():
    in_w = 1920
    in_h = 1080
    # target resolution 1080x1920 (9:16 aspect ratio)
    out_w = int(round(in_h * 1080.0 / 1920.0))
    # face in center
    cx = in_w / 2
    x = _compute_crop_x(in_w, in_h, out_w, cx)
    assert 0 <= x <= in_w - out_w


def test_compute_crop_left_edge():
    in_w = 1280
    in_h = 720
    # target resolution 1080x1920 (9:16 aspect ratio)
    out_w = int(round(in_h * 1080.0 / 1920.0))
    cx = 10  # face near left edge
    x = _compute_crop_x(in_w, in_h, out_w, cx)
    assert x == 0


def test_compute_crop_y_is_centered():
    in_h = 1080
    out_h = 1920
    crop_h = 1080
    cy = in_h / 2
    y = _compute_crop_y(in_h, crop_h, cy)
    assert y == 0

    in_h = 1920
    crop_h = 1080
    cy = 960
    y = _compute_crop_y(in_h, crop_h, cy)
    assert y == 420


def test_export_clips_accepts_transition_and_guest_metadata(tmp_path):
    result = export_clips(
        "dummy.mp4",
        [],
        str(tmp_path),
        transitions={"enabled": True, "type": "zoom_in"},
        guest_info={"name": "Test Guest"},
    )
    assert result == []


def test_guest_overlay_is_disabled_by_default():
    assert _build_guest_overlay({"name": "Test Guest"}, 1080, 1920) == ""
    assert _build_guest_overlay({"name": "Test Guest", "show_text_overlay": True}, 1080, 1920) == ""


def test_three_band_layout_uses_requested_percentages():
    layout = _build_three_band_filter(1120, 1920, {"title": "Topic"}, 20.0)
    assert "scale=1120:1440" in layout
    assert "crop=1120:1440" in layout
    assert "1120x58" in layout
    assert "scale=1120:422:force_original_aspect_ratio=disable,setsar=1[bottom_image]" in layout
    assert "overlay=x='(W-w)/2':y='H-h':shortest=1[image]" in layout
    assert "text='Topic'" in layout


def test_reference_template_supports_white_blue_bottom_background():
    layout = _build_reference_template_filter(
        1120,
        1920,
        {
            "title": "Title",
            "top_height": 170,
            "video_height": 900,
            "title_height": 300,
            "subscribe_height": 200,
            "bottom_background": "white_blue",
        },
        20.0,
        False,
    )
    assert "drawbox=x=0:y=175:w=1120:h=175" in layout
    assert "[top][main][title][bottom][subscribe]vstack=inputs=5" in layout


def test_image_fit_never_pads_beyond_panel_dimensions():
    layout = _build_image_fit_filter("[1:v]", "[bottom]", 1120, 273)
    assert "scale=w='ceil(max(1120,iw*273/ih)/2)*2':h='ceil(max(273,ih*1120/iw)/2)*2'" in layout
    assert "crop=1120:273:x='(iw-ow)/2':y='ih-oh'[bottom]" in layout


def test_reference_template_bottom_image_is_bottom_aligned():
    layout = _build_reference_template_filter(
        1120,
        1920,
        {
            "title": "Title",
            "top_height": 170,
            "video_height": 900,
            "title_height": 300,
            "subscribe_height": 200,
            "bottom_background": "image",
        },
        20.0,
        True,
    )
    assert "overlay=x='(W-w)/2':y='H-h':shortest=1[bottom]" in layout
    assert "scale=w='ceil(max(1120,iw*" in layout


def test_find_font_file_prefers_custom_font_when_available(tmp_path):
    font_file = tmp_path / "custom_font.ttf"
    font_file.write_bytes(b"fake-font-data")
    assert _find_font_file(str(font_file)) == str(font_file)


def test_requested_clip_count_must_match_generated_results():
    try:
        runner.validate_requested_clip_count(3, [{"file": "a.mp4"}, {"file": "b.mp4"}])
        raise AssertionError("Expected validation to fail when fewer clips are generated")
    except RuntimeError as exc:
        assert "Requested: 3" in str(exc)
        assert "Generated: 2" in str(exc)
