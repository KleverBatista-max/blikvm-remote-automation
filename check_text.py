#!/usr/bin/env python3
"""Check that some text is visible in a region of the remote screen (OCR). Exit code 0 = found, 1 = missing.

  python check_text.py --expect Ready --roi 1600,200,300,200
  python check_text.py --image shot.png --expect Ready --on-fail "echo ALERT"
"""
import argparse
import json
import os
import subprocess
import sys

from PIL import Image, ImageOps
import pytesseract

from blikvm import BliKVM


def crop_region(img, x, y, w, h):
    return img.crop((x, y, x + w, y + h))


def preprocess_for_ocr(im):
    im = im.resize((im.width * 2, im.height * 2), Image.LANCZOS).convert("L")
    im = ImageOps.autocontrast(im)
    return im.point(lambda p: 255 if p > 180 else 0)


def text_found(im, expect):
    text = pytesseract.image_to_string(im)
    return expect.lower() in text.lower(), text


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--expect", required=True, help="text that must be visible (case-insensitive)")
    ap.add_argument("--roi", default="0,0,1920,1080", help="x,y,w,h of the region to read")
    ap.add_argument("--image", help="use a local image instead of taking a screenshot")
    ap.add_argument("--on-fail", help="shell command to run when the text is NOT found (e.g. turn on an alert light)")
    ap.add_argument("--workdir", default=os.environ.get("BLIKVM_WORKDIR", os.path.expanduser("~/blikvm-captures")))
    ap.add_argument("--debug", action="store_true", help="save the cropped and preprocessed images")
    a = ap.parse_args()

    os.makedirs(a.workdir, exist_ok=True)
    path = a.image or BliKVM().login().screenshot(os.path.join(a.workdir, "latest_text.jpg"))
    x, y, w, h = (int(v) for v in a.roi.split(","))
    roi = crop_region(Image.open(path), x, y, w, h)
    pre = preprocess_for_ocr(roi)
    if a.debug:
        roi.save(os.path.join(a.workdir, "ocr_roi.png")); pre.save(os.path.join(a.workdir, "ocr_pre.png"))
    ok, raw = text_found(pre, a.expect)
    print(json.dumps({"source": path, "roi": [x, y, w, h], "expect": a.expect, "found": ok}, ensure_ascii=False))
    if not ok and a.on_fail:
        subprocess.run(a.on_fail, shell=True, timeout=30)   # runs a command YOU wrote; never fed from the screen text
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
