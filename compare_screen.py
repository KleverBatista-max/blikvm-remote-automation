"""Compare a BliKVM screenshot with a reference image, region by region (ROI).

Per ROI: block-wise SSIM (worst blocks dropped), colour-histogram correlation and the fraction of changed pixels.
Exit code 0 = the screen matches the reference, 1 = it does not.
"""
#!/usr/bin/env python3
import os, sys, json, requests, numpy as np
from datetime import datetime
from PIL import Image, ImageFilter

# ====== CONFIG (environment variables, no credentials in the code) ======
BASE = os.environ.get("BLIKVM_URL", "https://blikvm.local")
USER = os.environ.get("BLIKVM_USER", "admin")
PASS = os.environ.get("BLIKVM_PASS", "")
WORKDIR = os.environ.get("BLIKVM_WORKDIR", os.path.expanduser("~/blikvm-captures"))
CAPTURE_PATH = os.path.join(WORKDIR, "latest.jpg")
CONFIG_JSON = os.environ.get("BLIKVM_ROIS", os.path.join(WORKDIR, "rois.json"))   # see examples/rois.example.json
os.makedirs(WORKDIR, exist_ok=True)

ROI_PASS_THRESHOLD = 0.72   # minimum score per ROI (0..1) to count as a match
MAJORITY_K = 2              # how many ROIs must pass
SEARCH_OFFSET = 3           # +/- pixels searched to align the capture
DIFF_THRESH = 25            # per-pixel difference (0..255) that counts as "changed"
MAX_DIFF_RATIO = 0.015      # if more than 1.5% of an ROI changed, that ROI fails


def login(sess):
    r = sess.post(f"{BASE}/api/login",
                  json={"username": USER, "password": PASS},
                  timeout=10, verify=False)
    r.raise_for_status()
    data = r.json()
    token = (data.get("data") or {}).get("token") or data.get("token")
    if not token:
        raise RuntimeError("no token in /api/login response")
    sess.headers.update({"Authorization": f"Bearer {token}", "x-access-token": token})

def snap(sess):
    r = sess.get(f"{BASE}/api/video/screenshot", timeout=12, verify=False)
    r.raise_for_status()
    with open(CAPTURE_PATH, "wb") as f:
        f.write(r.content)
    return CAPTURE_PATH

def imread_gray_pil(path):
    img = Image.open(path).convert("L")
    return np.asarray(img, dtype=np.float64), img

def crop_np(arr, x, y, w, h):
    H, W = arr.shape[:2]
    x2, y2 = x + w, y + h
    x = max(0, min(x, W-1)); y = max(0, min(y, H-1))
    x2 = max(1, min(x2, W));  y2 = max(1, min(y2, H))
    return arr[y:y2, x:x2]

def crop_img(img, x, y, w, h):
    W, H = img.size
    x2, y2 = x + w, y + h
    x = max(0, min(x, W-1)); y = max(0, min(y, H-1))
    x2 = max(1, min(x2, W)); y2 = max(1, min(y2, H))
    return img.crop((x, y, x2, y2))

def resize_np(arr, new_w, new_h):
    im = Image.fromarray(arr.astype(np.uint8))
    im = im.resize((new_w, new_h), Image.BILINEAR)
    return np.asarray(im, dtype=np.float64)

# ---- SSIM sin OpenCV ----
def gaussian_blur_np(arr, radius):
    im = Image.fromarray(arr.astype(np.uint8))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(radius=radius)), dtype=np.float64)

def ssim_np(img1, img2):
    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2
    mu1 = gaussian_blur_np(img1, 1.5)
    mu2 = gaussian_blur_np(img2, 1.5)
    mu1_sq = mu1 * mu1; mu2_sq = mu2 * mu2; mu1_mu2 = mu1 * mu2
    img1_sq = img1 * img1; img2_sq = img2 * img2; img12 = img1 * img2
    sigma1_sq = gaussian_blur_np(img1_sq, 1.5) - mu1_sq
    sigma2_sq = gaussian_blur_np(img2_sq, 1.5) - mu2_sq
    sigma12   = gaussian_blur_np(img12,   1.5) - mu1_mu2
    num = (2 * mu1_mu2 + C1) * (2 * sigma12 + C2)
    den = (mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2) + 1e-9
    return float(np.mean(num / den))
# ---------------------------------------------------------

def hist_corr_pil(imgA_rgb, imgB_rgb):
    imgA_hsv = imgA_rgb.convert("HSV")
    imgB_hsv = imgB_rgb.convert("HSV")
    def corr(channel):
        a = np.array(imgA_hsv.getchannel(channel)).ravel()
        b = np.array(imgB_hsv.getchannel(channel)).ravel()
        histA, _ = np.histogram(a, bins=32, range=(0,255), density=True)
        histB, _ = np.histogram(b, bins=32, range=(0,255), density=True)
        if np.std(histA) < 1e-12 or np.std(histB) < 1e-12:
            return 0.0
        return float(np.corrcoef(histA, histB)[0,1])  # -1..1
    c = (corr(0) + corr(1)) / 2.0
    return max(0.0, min((c + 1.0)/2.0, 1.0))  # -> 0..1

def robust_ssim_blocks(A2, B2, grid=4, drop_k=2):
    h, w = A2.shape
    bh, bw = max(8, h // grid), max(8, w // grid)
    vals = []
    for gy in range(0, h, bh):
        for gx in range(0, w, bw):
            y1 = min(h, gy+bh); x1 = min(w, gx+bw)
            if (y1-gy) < 8 or (x1-gx) < 8: 
                continue
            vals.append(ssim_np(A2[gy:y1, gx:x1], B2[gy:y1, gx:x1]))
    if not vals:
        return 0.0
    vals.sort()
    if drop_k > 0 and len(vals) > drop_k:
        vals = vals[:-drop_k]  # descarta los peores (cursor/artefactos pequeños)
    return float(np.median(np.array(vals)))

def diff_ratio(A2, B2, thr=DIFF_THRESH):
    # porcentaje de píxeles cuyo |delta| > thr
    D = np.abs(A2 - B2)
    return float((D > thr).mean())

def best_roi_score(ref_gray, cap_gray, ref_rgb, cap_rgb, r, sx, sy, search_off):
    # recortes base de referencia
    A  = crop_np(ref_gray, r["x"], r["y"], r["w"], r["h"])
    Ar = crop_img(ref_rgb, r["x"], r["y"], r["w"], r["h"]).convert("RGB")
    if A.size == 0:
        return 0.0, 0.0, 0.0, 0.0, (0,0)

    best = (-1.0, 0.0, 0.0, 1.0, (0,0))  # (score, ssim, hist, diff, (dx,dy))
    bx0 = int(round(r["x"]*sx)); by0 = int(round(r["y"]*sy))
    bw  = int(round(r["w"]*sx)); bh  = int(round(r["h"]*sy))

    for dy in range(-search_off, search_off+1):
        for dx in range(-search_off, search_off+1):
            B  = crop_np(cap_gray, bx0+dx, by0+dy, bw, bh)
            Br = crop_img(cap_rgb,  bx0+dx, by0+dy, bw, bh).convert("RGB")
            if B.size == 0:
                continue
            tw = min(A.shape[1], B.shape[1], 300); th = min(A.shape[0], B.shape[0], 300)
            if tw < 8 or th < 8:
                continue
            A2 = resize_np(A, tw, th); B2 = resize_np(B, tw, th)
            ssim_v = robust_ssim_blocks(A2, B2, grid=4, drop_k=2)    # 0..1
            hcorr  = hist_corr_pil(Ar, Br)                           # 0..1
            dr     = diff_ratio(A2, B2, DIFF_THRESH)                 # 0..1
            score  = 0.7*max(0.0, min(ssim_v, 1.0)) + 0.3*hcorr

            # Guard-rail: si cambia > MAX_DIFF_RATIO del ROI, el ROI falla.
            if dr > MAX_DIFF_RATIO:
                score = 0.0

            # Bonus: si la estructura es casi perfecta, asegura buen score
            if ssim_v >= 0.995 and dr <= 0.002:
                score = max(score, 0.95)

            if score > best[0]:
                best = (score, ssim_v, hcorr, dr, (dx,dy))

    if best[0] < 0:
        return 0.0, 0.0, 0.0, 1.0, (0,0)
    return best

def compare_rois(ref_gray, cap_gray, ref_rgb, cap_rgb, rois, ref_size, search_off):
    ref_w, ref_h = ref_size
    Hc, Wc = cap_gray.shape[:2]
    sx, sy = Wc / ref_w, Hc / ref_h
    scores, details = [], []
    for r in rois:
        score, ssim_v, hcorr, dr, (dx,dy) = best_roi_score(ref_gray, cap_gray, ref_rgb, cap_rgb, r, sx, sy, search_off)
        scores.append(score)
        details.append({
            "name": r.get("name",""),
            "ssim": round(ssim_v,4),
            "hist": round(hcorr,4),
            "diff_ratio": round(dr,4),
            "score": round(score,4),
            "best_offset": [dx, dy]
        })
    global_score = float(np.median(np.array(scores))) if scores else 0.0
    return details, global_score

def main():
    requests.packages.urllib3.disable_warnings()
    if not os.path.exists(CONFIG_JSON):
        print(f"[ERROR] missing {CONFIG_JSON} (copy examples/rois.example.json)", file=sys.stderr); sys.exit(1)

    cfg = json.load(open(CONFIG_JSON, "r", encoding="utf-8"))
    ref_image_name = cfg.get("ref_image", "screenshot.png")
    ref_size = tuple(cfg["ref_size"])
    rois = cfg["rois"]

    ref_path = os.path.join(os.path.dirname(CONFIG_JSON), ref_image_name)
    if not os.path.exists(ref_path):
        print(f"[ERROR] missing reference image: {ref_path}", file=sys.stderr); sys.exit(1)

    s = requests.Session(); login(s); snap(s)

    ref_gray_arr, ref_rgb_im = imread_gray_pil(ref_path)
    cap_gray_arr, _          = imread_gray_pil(CAPTURE_PATH)
    cap_rgb_im               = Image.open(CAPTURE_PATH).convert("RGB")

    details, gscore = compare_rois(ref_gray_arr, cap_gray_arr, ref_rgb_im.convert("RGB"), cap_rgb_im, rois, ref_size, SEARCH_OFFSET)

    # Mayoría de ROIs por encima del umbral
    roi_pass = sum(1 for d in details if d["score"] >= ROI_PASS_THRESHOLD)
    es_similar = (roi_pass >= MAJORITY_K)

    result = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ref_image": ref_path,
        "capture": CAPTURE_PATH,
        "global_score": round(gscore, 4),
        "roi_pass_threshold": ROI_PASS_THRESHOLD,
        "majority_k": MAJORITY_K,
        "roi_passed": roi_pass,
        "match": es_similar,
        "rois": details
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("MATCH (majority of ROIs passed)" if es_similar else "NO MATCH (majority of ROIs failed)")
    sys.exit(0 if es_similar else 1)   # so cron / shell can act on the result

if __name__ == "__main__":
    main()
