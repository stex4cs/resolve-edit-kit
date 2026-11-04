#!/usr/bin/env python3
"""Contact strips: N frames across [in,out] of each clip, labeled, for picking exact moments.

Usage: .venv/bin/python scripts/contact.py OUT.jpg [--n 6] [--h 280] --clip PATH IN OUT [--clip PATH IN OUT ...]
(paths may contain spaces; one row per clip; labels "<name> @<sec>")
"""
import io, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def main(argv):
    out = argv[0]; n = int(argv[argv.index("--n") + 1]) if "--n" in argv else 6; h = int(argv[argv.index("--h") + 1]) if "--h" in argv else 280
    clips = [(argv[i + 1], float(argv[i + 2]), float(argv[i + 3])) for i, a in enumerate(argv) if a == "--clip"]
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 15)
    def grab(job):
        path, t = job
        raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1", "-vf", f"scale=-2:{h}",
                              "-f", "image2pipe", "-c:v", "png", "-"], capture_output=True).stdout
        im = Image.open(io.BytesIO(raw)).convert("RGB"); d = ImageDraw.Draw(im)
        d.rectangle([0, 0, im.width, 17], fill=(0, 0, 0)); d.text((2, 1), f"{Path(path).stem[-12:]} @{t:.2f}", font=font, fill="yellow")
        return im
    jobs = [(p, a + (b - a) * k / max(1, n - 1)) for p, a, b in clips for k in range(n)]
    with ThreadPoolExecutor(8) as ex: ims = list(ex.map(grab, jobs))
    w = max(i.width for i in ims); sheet = Image.new("RGB", (n * (w + 2), len(clips) * (h + 2)), "white")
    for i, im in enumerate(ims): sheet.paste(im, ((i % n) * (w + 2), (i // n) * (h + 2)))
    sheet.save(out, quality=82); print(out, len(clips), "rows")

if __name__ == "__main__":
    main(sys.argv[1:])
