#!/usr/bin/env python3
"""QA of a rendered edit against its plan: loudness, per-shot shake, 4 fps contact sheets, frames around transitions.

Usage: .venv/bin/python scripts/qa_render.py plans/X.json RENDER.mov OUT_DIR
Prints: integrated LUFS / true peak, median shake and shots over 0.3 (ignore drone/transition false alarms
-> check them on the sheet), and writes OUT_DIR/sheet_*.jpg (4 fps) + OUT_DIR/transitions.jpg.
"""
import json, subprocess, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from sheet import make_sheet  # noqa: E402
import shake  # noqa: E402


def main(plan_p, render, out):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    plan = json.loads(Path(plan_p).read_text(encoding="utf-8"))
    clips = plan["tracks"][0]["clips"]
    err = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", render, "-af", "loudnorm=print_format=json", "-f", "null", "-"], capture_output=True, text=True).stderr
    j = json.loads(err[err.rfind("{"):err.rfind("}") + 1])
    print(f"loudness {j['input_i']} LUFS, true peak {j['input_tp']} dBTP (target ~ -14..-15 LUFS, <= -1 dBTP)")
    d = shake.analyze(render); jit = np.array(d["jitter"])
    ends = [c["at"] for c in clips[1:]] + [max(c["at"] + (c["out"] - c["in"]) * 100 / c.get("speed", 100) for c in clips)]
    vals = []
    for c, e in zip(clips, ends):
        a, b = int(c["at"] * 25) + 5, int(e * 25) - 5
        s = jit[a:b]; s = s[s < 90]
        if len(s) >= 3: vals.append((float(np.percentile(s, 90)), c["at"], c.get("note", "")[:40]))
    print(f"shake median {np.median([v for v, _, _ in vals]):.3f}; over 0.3: {[(round(v, 2), round(t, 2), n) for v, t, n in vals if v > 0.3]}")
    fr = out / "frames"; fr.mkdir(exist_ok=True)
    for f in fr.glob("*.jpg"): f.unlink()
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", render, "-vf", "fps=4,scale=-2:300", "-q:v", "4", str(fr / "%04d.jpg")], check=True)
    frames = sorted(fr.glob("*.jpg"))
    for k in range(0, len(frames), 50):
        make_sheet([(f, f"{(int(f.stem) - 1) / 4:.2f}") for f in frames[k:k + 50]], out / f"sheet_{k // 50 + 1}.jpg", cols=10, tile_h=300)
    items = []
    for c in clips:
        if "transition_in" not in c: continue
        for o in (-3, 0, 3):
            p = out / f"tr_{c['at']:06.2f}_{o:+d}.jpg"
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{c['at'] + o / 25:.3f}", "-i", render, "-frames:v", "1", "-vf", "scale=-2:260", str(p)], check=True)
            items.append((p, f"{c['transition_in']['type'][:10]} {c['at']:.1f}{o:+d}f"))
    if items: make_sheet(items, out / "transitions.jpg", cols=9, tile_h=260)
    print(f"sheets: {out}/sheet_*.jpg, {out}/transitions.jpg")


if __name__ == "__main__":
    main(*sys.argv[1:4])
