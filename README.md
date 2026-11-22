# BliKVM remote automation

A small Python toolkit for a **[BliKVM](https://blikvm.com/)** (KVM-over-IP on a Raspberry Pi): log in through its web API, take screenshots of the remote machine, click and paste text, **check that the screen looks the way it should** (region-by-region image comparison) and **read text off the screen with OCR**. Meant to run from cron on any small Linux box next to the BliKVM.

The use case that started it: a remote PC that has to be in a known state every morning. If the screen doesn't match the reference, or an expected word isn't visible, the script exits non-zero and can run a command of yours (send an e-mail, switch on a status light, whatever).

## What's in here

| File | What it does |
|---|---|
| `blikvm.py` | Minimal client: `login()`, `screenshot(path)`, `click(x, y)`, `paste(text)` |
| `compare_screen.py` | Compares a fresh screenshot with a reference image, by regions (ROIs). Exit code `0` = matches, `1` = doesn't |
| `check_text.py` | OCR a region of the screen and check for an expected text. Exit code `0` = found, `1` = missing, optional `--on-fail "<command>"` |
| `click.py` | `python click.py 847 530`: log in and click a coordinate |
| `examples/` | ROI config, cron schedule, environment file |
| `tests/` | 15 tests that run **without any hardware** (a fake BliKVM server and synthetic images) |

## BliKVM API endpoints used

| Call | Purpose |
|---|---|
| `POST /api/login` `{"username","password"}` | returns a token (`data.token`); sent back as `Authorization: Bearer` and `x-access-token` |
| `GET /api/video/screenshot` | current frame of the remote screen |
| `POST /api/mouse/event` `{"x","y","action":"move"}` / `{"x","y","button":"left","action":"click"}` | mouse |
| `POST /api/hid/paste` `{"text","lang"}` | types text on the remote keyboard |

The BliKVM uses a self-signed certificate, so TLS verification is off by default (`verify=False`). Keep it on your LAN or VPN, not on the internet.

## How the comparison works

You pick a few **regions of interest** (ROIs) that must look the same as in a reference screenshot (a login box, a title bar, a status panel). For each ROI the script computes:

- a **block-wise SSIM** (the ROI is split in a 4×4 grid and the two worst blocks are dropped, so a blinking cursor or a clock doesn't fail the whole region),
- a **colour-histogram correlation**,
- the **fraction of changed pixels**, which is a hard guard-rail: more than 1.5 % changed and the ROI fails.

`score = 0.7 × SSIM + 0.3 × histogram`, searched over ±3 px of offset to absorb small shifts. A region passes at `score ≥ 0.72`; the screen matches when at least `MAJORITY_K` (default 2) regions pass. All thresholds are constants at the top of `compare_screen.py`.

## Quick start

```bash
git clone https://github.com/KleverBatista-max/blikvm-remote-automation && cd blikvm-remote-automation
pip install -r requirements.txt            # OCR also needs the tesseract binary: sudo apt install tesseract-ocr
cp examples/blikvm.env.example ~/.blikvm.env && chmod 600 ~/.blikvm.env   # edit URL / user / password
set -a; . ~/.blikvm.env; set +a

python click.py 847 530                    # sanity check: log in and click
mkdir -p ~/blikvm-captures
python -c "from blikvm import BliKVM; BliKVM().login().screenshot('$HOME/blikvm-captures/reference.png')"
cp examples/rois.example.json ~/blikvm-captures/rois.json    # edit the ROIs for your screen
python compare_screen.py                   # prints a JSON report; exit code 0 = match
python check_text.py --expect Ready --roi 1600,200,300,200 --debug
```

Credentials are read from `BLIKVM_URL`, `BLIKVM_USER` and `BLIKVM_PASS`; nothing is stored in the code. `--debug` saves the cropped and pre-processed OCR images so you can tune the region. For a schedule see `examples/crontab.example`.

## Tests

```bash
pip install -r requirements-dev.txt && pytest
```

They spin up a local fake BliKVM, so they check the login/token flow, clicks, paste, the screenshot download, the comparison (same screen matches, altered regions don't) and the exit codes, all without a device.

## Safety notes

- A BliKVM gives **full control** of the remote machine. Use a strong password, keep it off the internet, and keep the env file at mode `0600`.
- `--on-fail` runs a shell command **you** wrote; it is never built from text read off the screen.

## Status

I rebuilt this repository in November 2026 from my saved logs after wiping the Raspberry Pi where the originals ran. The algorithm and the endpoints are the ones I used in 2025 on a BliKVM v4; the tests above pass, but **I haven't run it against a real BliKVM since the rebuild**, so check it on yours before relying on it.

MIT licensed.
