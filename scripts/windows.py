#!/usr/bin/env python3
"""Steady + moving-camera windows from shake.py output.

Usage: .venv/bin/python scripts/windows.py SHAKE_DIR OUT.json [--min 0.8]
OUT.json: {clip: {"steady": [[in, out, len, jitter_p90, speed], ...], "move": [[in, out, speed, jitter_p90], ...]}}
- steady: camera still (jitter < 0.30/frame, p90 < 0.18, speed < 0.9)  -> safe for any use
- move:   smooth intentional camera move (slide/pan/drone; speed 0.25-2.5, jitter p90 < 0.18)  -> "cinematic" shots
Sorted best-first. 0.2 s at both clip ends is always excluded.
"""
import json, sys
from pathlib import Path
import numpy as np

def _runs(good):
    i, n = 0, len(good)
    while i < n:
        if not good[i]: i += 1; continue
        k = i
        while k < n and good[k]: k += 1
        yield i, k
        i = k

def windows(d, min_len=0.8):
    fps = d["fps"]; j = np.array(d["jitter"]); s = np.array(d["speed"]); n = len(j); e = int(0.2 * fps)
    out = {"steady": [], "move": []}
    g = (j < 0.30) & (s < 0.9); g[:e] = False; g[n - e:] = False
    for a, b in _runs(g):
        if (b - a) / fps >= min_len and np.percentile(j[a:b], 90) < 0.18:
            out["steady"].append([round(a / fps, 2), round(b / fps, 2), round((b - a) / fps, 2), round(float(np.percentile(j[a:b], 90)), 3), round(float(s[a:b].mean()), 2)])
    g = (j < 0.25) & (s >= 0.25) & (s <= 2.5); g[:e] = False; g[n - e:] = False
    for a, b in _runs(g):
        if (b - a) / fps >= min(0.6, min_len) and np.percentile(j[a:b], 90) < 0.18:
            out["move"].append([round(a / fps, 2), round(b / fps, 2), round(float(s[a:b].mean()), 2), round(float(np.percentile(j[a:b], 90)), 3)])
    out["steady"].sort(key=lambda w: -w[2]); out["move"].sort(key=lambda w: -(w[1] - w[0]) * w[2])
    return out

if __name__ == "__main__":
    mn = float(sys.argv[sys.argv.index("--min") + 1]) if "--min" in sys.argv else 0.8
    res = {f.stem: windows(json.loads(f.read_text()), mn) for f in sorted(Path(sys.argv[1]).glob("*.json"))}
    Path(sys.argv[2]).write_text(json.dumps(res, indent=1))
    print(f"{sum(1 for v in res.values() if v['steady'])} clips with steady, {sum(1 for v in res.values() if v['move'])} with moving windows, of {len(res)}")
