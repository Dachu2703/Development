from auto_shorts.export import _compute_crop_x


def test_compute_crop_center():
    in_w = 1920
    in_h = 1080
    out_w = int(round(in_h * 9.0 / 16.0))
    # face in center
    cx = in_w / 2
    x = _compute_crop_x(in_w, in_h, out_w, cx)
    assert 0 <= x <= in_w - out_w


def test_compute_crop_left_edge():
    in_w = 1280
    in_h = 720
    out_w = int(round(in_h * 9.0 / 16.0))
    cx = 10  # face near left edge
    x = _compute_crop_x(in_w, in_h, out_w, cx)
    assert x == 0
