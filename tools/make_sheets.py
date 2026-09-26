#!/usr/bin/env python3
"""Собирает контактные листы из дампа картинок: в порядке хендлов, с подписями."""
import csv, sys
from pathlib import Path
from PIL import Image, ImageDraw

src = Path(sys.argv[1]); out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
per_sheet = int(sys.argv[3]) if len(sys.argv) > 3 else 1200
cols = 40
scale = 4
cell = 16 * scale + 4      # картинка 16x16 (или другая) + рамка
label_h = 12
rows = per_sheet // cols

rows_csv = [r for r in csv.DictReader(open(src / "images.csv")) if r["file"]]
batches = [rows_csv[i:i+per_sheet] for i in range(0, len(rows_csv), per_sheet)]
for bi, batch in enumerate(batches):
    W = cols * cell
    H = rows * (cell + label_h)
    sheet = Image.new("RGB", (W, H), (30, 30, 40))
    dr = ImageDraw.Draw(sheet)
    for idx, r in enumerate(batch):
        cx = (idx % cols) * cell
        cy = (idx // cols) * (cell + label_h)
        img = Image.open(src / "images" / r["file"]).convert("RGBA")
        img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
        img = img.crop((0, 0, min(img.width, cell - 4), min(img.height, cell - 4)))
        bg = Image.new("RGBA", img.size, (60, 60, 75, 255))
        bg.alpha_composite(img)
        sheet.paste(bg.convert("RGB"), (cx + 2, cy + 2))
        if int(r["handle"]) % cols == 0 or idx == 0:
            dr.text((cx + 2, cy + cell), r["handle"], fill=(255, 255, 120))
    p = out / f"sheet_{bi:02d}.png"
    sheet.save(p)
    first, last = batch[0]["handle"], batch[-1]["handle"]
    print(f"{p}  хендлы {first}..{last}")
