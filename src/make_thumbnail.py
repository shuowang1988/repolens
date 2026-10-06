"""Generate the 560x280 Kaggle Writeup card/thumbnail image.

Light background, big title, mini 3x3 overlap schematic (same numbers as
fig1: 0.371 / 0.405 / 0.322, re-derived in derive_truth.py). Run:
  python make_thumbnail.py
Output: runs/figures/thumbnail_560x280.png (exactly 560x280).
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 560, 280
OUT = Path(__file__).resolve().parent.parent / "runs" / "figures" / "thumbnail_560x280.png"

ARIAL = Path(r"C:\Windows\Fonts\arial.ttf")
ARIAL_BD = Path(r"C:\Windows\Fonts\arialbd.ttf")


def font(bold: bool, size: int):
    p = ARIAL_BD if bold else ARIAL
    try:
        return ImageFont.truetype(str(p), size)
    except Exception:
        return ImageFont.load_default()


def main() -> None:
    img = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(img)
    # thin border so the card has an edge on white pages
    d.rectangle([0, 0, W - 1, H - 1], outline="#D9E1EA", width=2)

    # ---- left: title block ----
    d.text((28, 30), "RepoLens", font=font(True, 58), fill="#0F1E2E")
    d.rectangle([30, 108, 94, 113], fill="#2E7BD6")
    d.text((28, 124), "Interpretable Structural", font=font(False, 20), fill="#333A44")
    d.text((28, 150), "Similarity for Repositories", font=font(False, 20), fill="#333A44")
    d.text((28, 186), "41 repos \u00b7 8 components \u00b7 stdlib-only",
           font=font(False, 15), fill="#5A6B7C")
    d.text((28, 212), "deterministic \u00b7 explainable \u00b7 offline",
           font=font(False, 15), fill="#5A6B7C")
    d.text((28, 244), "Top-5 overlap struct vs content: 0.371",
           font=font(True, 14), fill="#174A7C")

    # ---- right: mini overlap schematic ----
    d.rounded_rectangle([340, 20, 534, 260], radius=14, fill="#F0F4F8", outline="#D5DEE7", width=2)
    t = "Top-5 overlap"
    bb = d.textbbox((0, 0), t, font=font(True, 14))
    d.text(((340 + 534 - (bb[2] - bb[0])) / 2, 30), t, font=font(True, 14), fill="#33475B")

    vals = [[1.0, 0.371, 0.405],
            [0.371, 1.0, 0.322],
            [0.405, 0.322, 1.0]]
    fills = {(0, 0): "#174A7C", (1, 1): "#174A7C", (2, 2): "#174A7C",
             (0, 1): "#BFD4E8", (1, 0): "#BFD4E8",
             (0, 2): "#A9C6E1", (2, 0): "#A9C6E1",
             (1, 2): "#D8E5F2", (2, 1): "#D8E5F2"}
    cell, gap = 44, 5
    gw = 3 * cell + 2 * gap
    ox = int(340 + (194 - gw) / 2)
    oy = 56
    for r in range(3):
        for c in range(3):
            x0, y0 = ox + c * (cell + gap), oy + r * (cell + gap)
            d.rounded_rectangle([x0, y0, x0 + cell, y0 + cell], radius=7, fill=fills[(r, c)])
            v = vals[r][c]
            s = "1.00" if v == 1.0 else f"{v:.3f}"
            fnt = font(True, 13)
            bb2 = d.textbbox((0, 0), s, font=fnt)
            fill = "#FFFFFF" if v == 1.0 else "#1A2E44"
            d.text((x0 + (cell - (bb2[2] - bb2[0])) / 2, y0 + (cell - (bb2[3] - bb2[1])) / 2 - 1),
                   s, font=fnt, fill=fill)
    cap = "41 repositories"
    bb3 = d.textbbox((0, 0), cap, font=font(False, 12))
    d.text(((340 + 534 - (bb3[2] - bb3[0])) / 2, 226), cap,
           font=font(False, 12), fill="#5A6B7C")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG")
    print(f"wrote {OUT} size={img.size}")


if __name__ == "__main__":
    main()
