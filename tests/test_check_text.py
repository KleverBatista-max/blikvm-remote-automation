import sys

import numpy as np
import pytest
from PIL import Image

import check_text


def test_preprocess_is_binary_and_doubled():
    im = Image.new("RGB", (50, 20), (120, 200, 40))
    out = check_text.preprocess_for_ocr(im)
    assert out.size == (100, 40) and set(np.unique(np.array(out)).tolist()) <= {0, 255}


@pytest.mark.parametrize("text, expect, found", [("Status: READY ok", "ready", True), ("nothing here", "ready", False)])
def test_text_found_is_case_insensitive(monkeypatch, text, expect, found):
    monkeypatch.setattr(check_text.pytesseract, "image_to_string", lambda im: text)
    assert check_text.text_found(Image.new("L", (10, 10)), expect)[0] is found


def run(monkeypatch, tmp_path, argv):
    img = tmp_path / "s.png"; Image.new("RGB", (200, 100), "white").save(img)
    monkeypatch.setattr(sys, "argv", ["check_text.py", "--image", str(img), "--workdir", str(tmp_path)] + argv)
    with pytest.raises(SystemExit) as e:
        check_text.main()
    return e.value.code


def test_found_exits_zero_and_skips_the_fail_command(monkeypatch, tmp_path):
    monkeypatch.setattr(check_text.pytesseract, "image_to_string", lambda im: "ready")
    flag = tmp_path / "alert"
    assert run(monkeypatch, tmp_path, ["--expect", "ready", "--on-fail", f"touch {flag}"]) == 0 and not flag.exists()


def test_missing_text_exits_one_and_runs_the_fail_command(monkeypatch, tmp_path):
    monkeypatch.setattr(check_text.pytesseract, "image_to_string", lambda im: "something else")
    flag = tmp_path / "alert"
    assert run(monkeypatch, tmp_path, ["--expect", "ready", "--on-fail", f"touch {flag}"]) == 1 and flag.exists()
