#!/usr/bin/env python3
"""Render docs/img/pipeline.png — the Drop & Play flow, drawn by this repo.

Re-run after edits:
    python3 tools/make_pipeline_diagram.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "img" / "pipeline.png"
FDIR = "/usr/share/fonts/liberation"

S = 2                                   # supersample factor
BW, BH, GAP = 158 * S, 84 * S, 38 * S
CONTENT_W = 6 * BW + 5 * GAP
W = CONTENT_W + 48 * S                 # room for all six boxes + margins
H = 300 * S
X0 = (W - CONTENT_W) // 2
NAVY = (12, 30, 66)
ACCENT = (28, 78, 132)
BODY = (34, 34, 38)
BOX_BG = (232, 240, 250)
BOX_ED = (28, 78, 132)
SOFT = (110, 116, 124)
PAPER = (255, 255, 255)

img = Image.new("RGB", (W, H), PAPER)
d = ImageDraw.Draw(img)


def F(sz, bold=False):
    return ImageFont.truetype(
        f"{FDIR}/LiberationSans-{'Bold' if bold else 'Regular'}.ttm".replace("ttm", "ttf"), sz)


def rrect(x, y, w, h, r, fill, outline, width=2):
    d.rounded_rectangle([x, y, x + w, y + h], radius=r,
                        fill=fill, outline=outline, width=width)


def ctext(cx, cy, text, font, fill):
    l, t, r_, b = d.textbbox((cx, cy), text, font=font, anchor="mm")
    d.text(((l + r_) / 2, (t + b) / 2), text, font=font, fill=fill, anchor="mm")


def arrow(x1, y1, x2, y2, color=ACCENT, wd=3 * S, head=9 * S):
    import math
    d.line([x1, y1, x2, y2], fill=color, width=wd)
    ang = math.atan2(y2 - y1, x2 - x1)
    for s in (0.4, -0.4):
        d.polygon([(x2, y2),
                   (x2 - head * math.cos(ang + s), y2 - head * math.sin(ang + s)),
                   (x2 - head * math.cos(ang - s), y2 - head * math.sin(ang - s))],
                  fill=color)


# ---- title -------------------------------------------------------------
ctext(W / 2, 26 * S, "From your game file to a native PC program — no emulator",
      F(17 * S, True), NAVY)
d.line([20 * S, 44 * S, W - 20 * S, 44 * S], fill=(188, 198, 210), width=S)

# ---- boxes -------------------------------------------------------------
Y0 = 92 * S
steps = [
    ("1", "YOUR DISC", ".ecm / .bin / .cue"),
    ("2", "UNSQUEEZE", "bundled unecm"),
    ("3", "BIN + CUE", "verified 5-track layout"),
    ("4", "TRANSLATE", "psxrecomp: MIPS → C"),
    ("5", "COMPILE", "cmake + gcc, ~3 min"),
]
PLAY = ("6", "PLAY!", "native executable")
centers = []
for i, (num, big, small) in enumerate(steps):
    x = X0 + i * (BW + GAP)
    rrect(x, Y0, BW, BH, 10 * S, BOX_BG, BOX_ED)
    ctext(x + BW / 2, Y0 + 20 * S, num, F(15 * S, True), SOFT)
    ctext(x + BW / 2, Y0 + 44 * S, big, F(16 * S, True), NAVY)
    ctext(x + BW / 2, Y0 + 64 * S, small, F(11 * S), BODY)
    centers.append((x + BW, x + BW / 2))

# 6th box: PLAY (accent-filled)
x = X0 + 5 * (BW + GAP)
rrect(x, Y0, BW, BH, 10 * S, NAVY, NAVY)
ctext(x + BW / 2, Y0 + 20 * S, "6", F(15 * S, True), (150, 170, 205))
ctext(x + BW / 2, Y0 + 44 * S, "PLAY!", F(17 * S, True), PAPER)
ctext(x + BW / 2, Y0 + 64 * S, "straight into the game", F(10 * S), (200, 214, 235))

# arrows between boxes
for i in range(5):
    ax1 = X0 + i * (BW + GAP) + BW + 3 * S
    ax2 = X0 + (i + 1) * (BW + GAP) - 3 * S
    ay = Y0 + BH / 2
    arrow(ax1, ay, ax2, ay)

# ---- footer band -------------------------------------------------------
FY = Y0 + BH + 26 * S
d.line([20 * S, FY - 8 * S, W - 20 * S, FY - 8 * S], fill=(188, 198, 210), width=S)
ctext(W / 2, FY + 10 * S, "No emulator runs the game: the disc's own MIPS code is translated once into C,",
      F(12 * S), BODY)
ctext(W / 2, FY + 30 * S, "compiled by gcc — with recompiled OpenBIOS as the kernel and a C++ runtime in place of the console's other chips.",
      F(12 * S), BODY)
ctext(W / 2, FY + 52 * S, "tools/drop_and_play.py runs all six steps: drag your file, come back in ~10 minutes, play. After that: seconds.",
      F(11 * S), SOFT)

OUT.parent.mkdir(parents=True, exist_ok=True)
img = img.resize((W // S, H // S), Image.LANCZOS)
img.save(OUT, optimize=True)
print("wrote", OUT, img.size)