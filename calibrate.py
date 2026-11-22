#!/usr/bin/env python3
"""Find the coordinates you need for clicks and for regions (ROIs).

  python calibrate.py shot [-o reference.png]                 take a screenshot from the BliKVM
  python calibrate.py grid reference.png [--step 100]         overlay a labelled grid -> reference_grid.png
  python calibrate.py crop X Y W H [--ref reference.png] [--live live.png]
                                                              show what a candidate region looks like
  python calibrate.py rois [--config rois.json] [--live live.png]
                                                              crop every ROI of the config, reference vs live

All coordinates are pixels of the screenshot (the origin is the top-left corner, x grows to the right, y downwards).
"""
import argparse
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

from blikvm import BliKVM

WORKDIR = os.environ.get("BLIKVM_WORKDIR", os.path.expanduser("~/blikvm-captures"))
GREEN, RED, BLACK = (0, 255, 0), (255, 0, 0), (0, 0, 0)


def _font(size):
    try:
        return ImageFont.load_default(size=size)       # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def draw_grid(img, step=100):
    """Return a copy of `img` with a labelled grid: a line every `step` pixels, labels read in screenshot pixels."""
    im = img.convert("RGB")
    w, h = im.size
    d = ImageDraw.Draw(im)
    font = _font(max(12, w // 90))

    def label(xy, text):
        box = d.textbbox(xy, text, font=font)
        d.rectangle(box, fill=BLACK)                   # dark backing so the label is readable on any screen
        d.text(xy, text, fill=GREEN, font=font)

    for x in range(0, w, step):
        d.line([(x, 0), (x, h)], fill=GREEN, width=1)
        label((x + 3, 3), f"x={x}")
    for y in range(0, h, step):
        d.line([(0, y), (w, y)], fill=GREEN, width=1)
        label((3, y + 3), f"y={y}")
    d.rectangle([(0, 0), (w - 1, h - 1)], outline=RED, width=2)
    return im


def _clamped_crop(img, x, y, w, h):
    W, H = img.size
    x0, y0 = max(0, min(x, W - 1)), max(0, min(y, H - 1))
    x1, y1 = max(x0 + 1, min(x + w, W)), max(y0 + 1, min(y + h, H))
    return img.crop((x0, y0, x1, y1))


def crop_pair(ref, live, x, y, w, h, ref_size=None):
    """Crop the same region from the reference and from the live capture.

    If the live capture has another resolution than the reference, the region is scaled like the comparator does
    (compare_screen.py). `ref_size` is the size the coordinates were written for (default: the reference's own size).
    """
    rw, rh = ref_size or ref.size
    sx, sy = live.width / rw, live.height / rh
    a = _clamped_crop(ref, x, y, w, h)
    b = _clamped_crop(live, round(x * sx), round(y * sy), round(w * sx), round(h * sy))
    return a, b


def side_by_side(a, b, gap=10):
    out = Image.new("RGB", (a.width + gap + b.width, max(a.height, b.height)), (40, 40, 40))
    out.paste(a, (0, 0)); out.paste(b, (a.width + gap, 0))
    return out


def _live(path):
    if path:
        return Image.open(path).convert("RGB"), path
    p = BliKVM().login().screenshot(os.path.join(WORKDIR, "latest.jpg"))
    return Image.open(p).convert("RGB"), p


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shot"); s.add_argument("-o", "--out", default=os.path.join(WORKDIR, "reference.png"))
    g = sub.add_parser("grid"); g.add_argument("image"); g.add_argument("--step", type=int, default=100); g.add_argument("-o", "--out")
    c = sub.add_parser("crop")
    for n in "xywh": c.add_argument(n.upper(), type=int)
    c.add_argument("--ref", default=os.path.join(WORKDIR, "reference.png")); c.add_argument("--live"); c.add_argument("--outdir", default=os.path.join(WORKDIR, "debug"))
    r = sub.add_parser("rois"); r.add_argument("--config", default=os.environ.get("BLIKVM_ROIS", os.path.join(WORKDIR, "rois.json")))
    r.add_argument("--live"); r.add_argument("--outdir", default=os.path.join(WORKDIR, "debug"))
    a = ap.parse_args(argv)

    if a.cmd == "shot":
        print("saved", BliKVM().login().screenshot(a.out))
    elif a.cmd == "grid":
        out = a.out or os.path.splitext(a.image)[0] + "_grid.png"
        draw_grid(Image.open(a.image), a.step).save(out)
        print("saved", out, "- open it and read x/y off the grid lines")
    elif a.cmd == "crop":
        os.makedirs(a.outdir, exist_ok=True)
        ref = Image.open(a.ref).convert("RGB"); live, _ = _live(a.live)
        ra, lb = crop_pair(ref, live, a.X, a.Y, a.W, a.H)
        ra.save(os.path.join(a.outdir, "probe_ref.png")); lb.save(os.path.join(a.outdir, "probe_live.png"))
        side_by_side(ra, lb).save(os.path.join(a.outdir, "probe.png"))
        print("saved", os.path.join(a.outdir, "probe.png"), "(left: reference, right: live)")
    elif a.cmd == "rois":
        cfg = json.load(open(a.config, encoding="utf-8"))
        ref = Image.open(os.path.join(os.path.dirname(a.config), cfg.get("ref_image", "reference.png"))).convert("RGB")
        live, _ = _live(a.live)
        os.makedirs(a.outdir, exist_ok=True)
        for roi in cfg["rois"]:
            ra, lb = crop_pair(ref, live, roi["x"], roi["y"], roi["w"], roi["h"], tuple(cfg["ref_size"]))
            ra.save(os.path.join(a.outdir, f"ref_{roi['name']}.png")); lb.save(os.path.join(a.outdir, f"live_{roi['name']}.png"))
            side_by_side(ra, lb).save(os.path.join(a.outdir, f"roi_{roi['name']}.png"))
        print("saved", len(cfg["rois"]), "ROIs in", a.outdir)


if __name__ == "__main__":
    sys.exit(main())
