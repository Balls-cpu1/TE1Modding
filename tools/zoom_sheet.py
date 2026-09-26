import csv, sys
from pathlib import Path
from PIL import Image, ImageDraw
src, out, lo, hi = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
scale = 6; cols = 32
rows_csv = [r for r in csv.DictReader(open(src/"images.csv")) if r["file"] and lo <= int(r["handle"]) <= hi]
cell = 16*scale+6; lab = 16
per = cols*10
for bi in range(0, len(rows_csv), per):
    batch = rows_csv[bi:bi+per]
    W = cols*cell; H = (len(batch)//cols+1)*(cell+lab)
    sheet = Image.new("RGB",(W,H),(25,25,35)); dr = ImageDraw.Draw(sheet)
    for i,r in enumerate(batch):
        cx=(i%cols)*cell; cy=(i//cols)*(cell+lab)
        im = Image.open(src/"images"/r["file"]).convert("RGBA")
        im = im.resize((im.width*scale, im.height*scale), Image.NEAREST)
        bg = Image.new("RGBA", im.size, (55,55,70,255)); bg.alpha_composite(im)
        sheet.paste(bg.convert("RGB"), (cx+3, cy+3))
        dr.text((cx+3, cy+cell-1), r["handle"], fill=(255,255,140))
    p = out/f"zoom_{lo}_{bi:02d}.png"; sheet.save(p); print(p, f"{batch[0]['handle']}..{batch[-1]['handle']}")
