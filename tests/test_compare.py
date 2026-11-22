import importlib
import json

import numpy as np
import pytest
from PIL import Image

from conftest import FakeBliKVM, png_bytes

W, H = 640, 360
ROIS = [{"name": "a", "x": 40, "y": 40, "w": 200, "h": 80}, {"name": "b", "x": 300, "y": 40, "w": 200, "h": 80},
        {"name": "c", "x": 40, "y": 200, "w": 300, "h": 120}]


def reference():
    rng = np.random.default_rng(7)
    base = np.tile(np.linspace(30, 220, W, dtype=np.uint8), (H, 1))
    img = np.stack([base, base[::-1], np.roll(base, 90, axis=1)], axis=-1).astype(np.int16)
    img += rng.integers(-12, 12, size=img.shape)          # texture, so SSIM has something to compare
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def altered(img):
    a = np.array(img).copy()
    for r in ROIS:
        a[r["y"]:r["y"] + r["h"], r["x"]:r["x"] + r["w"]] = 255 - a[r["y"]:r["y"] + r["h"], r["x"]:r["x"] + r["w"]]
    return Image.fromarray(a)


@pytest.fixture
def cs(tmp_path, monkeypatch):
    monkeypatch.setenv("BLIKVM_WORKDIR", str(tmp_path / "work"))
    monkeypatch.setenv("BLIKVM_PASS", "good-pass")
    import compare_screen
    return importlib.reload(compare_screen)


def scores(cs, ref, cap, tmp_path):
    rp, cp = tmp_path / "ref.png", tmp_path / "cap.png"; ref.save(rp); cap.save(cp)
    rg, rrgb = cs.imread_gray_pil(str(rp)); cg, _ = cs.imread_gray_pil(str(cp))
    details, g = cs.compare_rois(rg, cg, rrgb.convert("RGB"), Image.open(cp).convert("RGB"), ROIS, (W, H), cs.SEARCH_OFFSET)
    return details, g


def test_same_screen_matches(cs, tmp_path):
    ref = reference(); details, g = scores(cs, ref, ref.copy(), tmp_path)
    assert all(d["score"] >= cs.ROI_PASS_THRESHOLD for d in details) and g > 0.9


def test_changed_regions_do_not_match(cs, tmp_path):
    ref = reference(); details, _ = scores(cs, ref, altered(ref), tmp_path)
    assert sum(d["score"] >= cs.ROI_PASS_THRESHOLD for d in details) < cs.MAJORITY_K


@pytest.mark.parametrize("cap_fn, code", [(lambda r: r.copy(), 0), (altered, 1)])
def test_end_to_end_exit_code(cs, tmp_path, monkeypatch, capsys, cap_fn, code):
    ref = reference(); work = tmp_path / "work"; work.mkdir(exist_ok=True)
    ref.save(work / "reference.png")
    (work / "rois.json").write_text(json.dumps({"ref_image": "reference.png", "ref_size": [W, H], "rois": ROIS}))
    fake = FakeBliKVM(png_bytes(cap_fn(ref)))
    try:
        monkeypatch.setattr(cs, "BASE", fake.url)
        with pytest.raises(SystemExit) as e:
            cs.main()
    finally:
        fake.close()
    out = capsys.readouterr().out
    assert e.value.code == code and ('"match": true' in out) == (code == 0)
