from auto_shorts.export import _build_guest_overlay, _build_three_band_filter, _compute_crop_x, _compute_crop_y, export_clips


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
    assert "scale=1120:422" in layout
    assert "pad=1120:422" in layout
    assert "text='Topic'" in layout
