from auto_shorts.export import (
    _build_bottom_image_filter,
    _build_image_fit_filter,
    _build_reference_template_filter,
    _build_three_band_filter,
)


def test_image_fit_filter_uses_cover_scaling_and_bottom_crop():
    image_filter = _build_image_fit_filter("[1:v]", "[image]", 1080, 480)

    assert "ceil(max(1080,iw*480/ih)/2)*2" in image_filter
    assert "ceil(max(480,ih*1080/iw)/2)*2" in image_filter
    assert "crop=1080:480:x='(iw-ow)/2':y='ih-oh'[image]" in image_filter


def test_three_band_banner_labels_drawtext_output():
    image_filter = _build_three_band_filter(1080, 1920, {"title": "Topic", "name": "Guest"}, 10.0)

    assert "y=(h-text_h)/2[banner]" in image_filter
    assert "d=10[banner],drawtext" not in image_filter

def test_three_band_filter_uses_selected_output_dimensions():
    image_filter = _build_three_band_filter(1080, 1920, None, 10.0)

    assert "color=c=black:s=1080x422" in image_filter
    assert "scale=1080:422:force_original_aspect_ratio=disable,setsar=1[bottom_image]" in image_filter


def test_bottom_image_is_scaled_to_exact_panel_rectangle():
    image_filter = _build_bottom_image_filter("[1:v]", "[bottom]", 1080, 480)

    assert image_filter == (
        "[1:v]scale=1080:480:force_original_aspect_ratio=disable,"
        "setsar=1[bottom]"
    )


def test_reference_template_bottom_image_is_composited_into_panel():
    image_filter = _build_reference_template_filter(
        1080,
        1920,
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

    assert "scale=1080:320:force_original_aspect_ratio=disable,setsar=1[bottom_image]" in image_filter
    assert "[bottom_bg][bottom_image]overlay" in image_filter