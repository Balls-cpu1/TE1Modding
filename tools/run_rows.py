import csv, sys
from pathlib import Path
from PIL import Image, ImageDraw
src = Path("dump_eur")
runs = [(1618,1686),(2065,2113),(2514,2556),(2596,2617),(2649,2749),(2763,2782),(2786,2813),
        (2882,2900),(2914,3037),(3039,3062),(3091,3210),(3219,3237),(3239,3257),(3264,3326),
        (3373,3390),(3392,3413),(3415,3481),(3500,3519),(3521,3622),(3636,3761),(3800,3821),
        (3823,3840),(3842,3858),(3940,3959)]
rows = {int(r["handle"]): r for r in csv.DictReader(open(src/"images.csv")) if r["file"]}
scale = 4; per_row = 60; cell = 16*scale+4; lab = 14
W = per_row*cell; H = len(runs)*(cell+lab)
sheet = Image.new("RGB",(W,H),(28,28,38)); dr = ImageDraw.Draw(sheet)
for ri,(a,b) in enumerate(runs):
    hs = sorted(h for h in rows if a <= h <= b)
    step = max(1, len(hs)//per_row)
    hs = hs[::step][:per_row]
    y = ri*(cell+lab)
    dr.text((4, y+cell), f"{a}..{b} ({len(hs)} из {b-a+1})", fill=(255,255,120))
    for i,h in enumerate(hs):
        im = Image.open(src/"images"/rows[h]["file"]).convert("RGBA")
        im = im.resize((im.width*scale, im.height*scale), Image.NEAREST)
        bg = Image.new("RGBA", im.size, (58,58,72,255)); bg.alpha_composite(im)
        sheet.paste(bg.convert("RGB"), (i*cell+2, y+2))
sheet.save("runs_overview.png"); print("runs_overview.png", sheet.size)
