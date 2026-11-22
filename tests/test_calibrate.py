import json

import numpy as np
import pytest
from PIL import Image

import calibrate
from conftest import FakeBliKVM, png_bytes


def img(w, h, color=(0, 0, 0)):
    return Image.new("RGB", (w, h), color)


def test_grid_lines_every_step_and_size_unchanged():
    out = calibrate.draw_grid(img(400, 300), step=100)
    assert out.size == (400, 300)
    a = np.array(out)
    assert tuple(a[150, 200]) == calibrate.GREEN          # on the x=200 vertical line, away from the labels
    assert tuple(a[100, 250]) == calibrate.GREEN          # on the y=100 horizontal line
    assert tuple(a[150, 250]) == (0, 0, 0)                # between lines: untouched


def test_grid_does_not_modify_the_input():
    src = img(200, 200); calibrate.draw_grid(src, 50)
    assert not np.array(src).any()                        # the original stays all black


def square(w, h, box, scale=1):
    im = img(w, h); x, y, bw, bh = (v * scale for v in box)
    im.paste((255, 0, 0), (x, y, x + bw, y + bh)); return im


def test_crop_pair_same_resolution():
    ref, live = square(400, 300, (100, 100, 50, 50)), square(400, 300, (100, 100, 50, 50))
    a, b = calibrate.crop_pair(ref, live, 100, 100, 50, 50)
    assert a.size == b.size == (50, 50) and a.getpixel((25, 25)) == b.getpixel((25, 25)) == (255, 0, 0)


def test_crop_pair_scales_when_the_live_capture_is_bigger():
    ref, live = square(400, 300, (100, 100, 50, 50)), square(800, 600, (100, 100, 50, 50), scale=2)
    a, b = calibrate.crop_pair(ref, live, 100, 100, 50, 50)
    assert a.size == (50, 50) and b.size == (100, 100) and b.getpixel((50, 50)) == (255, 0, 0)


def test_crop_outside_the_image_is_clamped_not_an_error():
    a, _ = calibrate.crop_pair(img(100, 100), img(100, 100), 90, 90, 50, 50)
    assert a.size == (10, 10)


def test_cli_grid_writes_the_default_name(tmp_path):
    p = tmp_path / "ref.png"; img(300, 200).save(p)
    calibrate.main(["grid", str(p), "--step", "50"])
    assert (tmp_path / "ref_grid.png").exists()


def test_cli_crop_and_rois_with_a_local_live_image(tmp_path):
    ref, live = tmp_path / "reference.png", tmp_path / "live.png"
    square(400, 300, (100, 100, 50, 50)).save(ref); square(400, 300, (100, 100, 50, 50)).save(live)
    out = tmp_path / "dbg"
    calibrate.main(["crop", "100", "100", "50", "50", "--ref", str(ref), "--live", str(live), "--outdir", str(out)])
    assert {f.name for f in out.iterdir()} == {"probe_ref.png", "probe_live.png", "probe.png"}
    cfg = tmp_path / "rois.json"
    cfg.write_text(json.dumps({"ref_image": "reference.png", "ref_size": [400, 300], "rois": [{"name": "box", "x": 100, "y": 100, "w": 50, "h": 50}]}))
    calibrate.main(["rois", "--config", str(cfg), "--live", str(live), "--outdir", str(out)])
    assert (out / "roi_box.png").exists() and Image.open(out / "roi_box.png").size == (110, 50)


def test_cli_shot_downloads_through_the_api(tmp_path, monkeypatch):
    fake = FakeBliKVM(png_bytes(img(64, 48, (9, 9, 9))))
    try:
        for k, v in (("BLIKVM_URL", fake.url), ("BLIKVM_USER", "admin"), ("BLIKVM_PASS", "good-pass")): monkeypatch.setenv(k, v)
        calibrate.main(["shot", "-o", str(tmp_path / "ref.png")])
    finally:
        fake.close()
    assert Image.open(tmp_path / "ref.png").size == (64, 48)
