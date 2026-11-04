#!/usr/bin/env python3
"""Offline simulation of a plan's audio mix (same files, positions, clip gains, fades as Resolve).

Reports integrated loudness (ffmpeg ebur128), true peak (4x oversampled) and peak timeline,
so clip gains can be set before rendering. Usage:
    .venv/bin/python scripts/mix_sim.py plans/wv3c.json [out.wav]
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parent.parent
SR = 48000


def load(path, t_in, t_out):
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t_in:.4f}", "-t", f"{t_out - t_in:.4f}",
                          "-i", str(path), "-vn", "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)


def frame(seconds, fps=25):
    return int(np.floor(seconds * fps + 0.5))


def mix(plan, fps=25):
    tracks = [t for t in plan["tracks"] if t["kind"] == "audio"]
    end = max(c["at"] + (c["out"] - c["in"]) for t in tracks for c in t["clips"]) + 1
    bus = np.zeros((int(end * SR), 2))
    stems = {}
    for t in tracks:
        stem = np.zeros_like(bus)
        for c in t["clips"]:
            path = Path(c["file"]) if Path(c["file"]).is_absolute() else ROOT / c["file"]
            # Resolve places on frame boundaries: mirror that quantization.
            at = frame(c["at"], fps) / fps
            t_in = frame(c["in"], fps) / fps
            length = (frame(c["at"] + c["out"] - c["in"], fps) - frame(c["at"], fps)) / fps
            a = load(path, t_in, t_in + length) * 10 ** (c.get("volume", 0) / 20)
            n = len(a)
            fi, fo = int(c.get("fade_in", 0) * SR), int(c.get("fade_out", 0) * SR)
            if fi:
                a[:fi] *= np.linspace(0, 1, fi)[:, None]
            if fo:
                a[n - fo:] *= np.linspace(1, 0, fo)[:, None]
            i = int(at * SR)
            stem[i:i + n] += a[: len(stem) - i]
        stems[t["name"]] = stem
        bus += stem
    return bus, stems


def true_peak_db(x):
    up = resample_poly(x, 4, 1, axis=0)
    return 20 * np.log10(np.abs(up).max() + 1e-12)


def loudness(x, tmp):
    import soundfile as sf
    sf.write(tmp, x, SR, subtype="FLOAT")
    err = subprocess.run(["ffmpeg", "-nostdin", "-i", tmp, "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    summary = err[err.rfind("Summary:"):]
    get = lambda key: float(summary.split(key)[1].split()[0])
    return get("I:"), get("LRA:")


def report(plan, out=None):
    bus, stems = mix(plan)
    tmp = out or "/tmp/mix_sim.wav"
    i_lufs, lra = loudness(bus, tmp)
    tp = true_peak_db(bus)
    print(f"integrated {i_lufs:.1f} LUFS, LRA {lra:.1f}, true peak {tp:+.2f} dBTP")
    win = SR // 4
    hot = [(k / SR, 20 * np.log10(np.abs(bus[k:k + win]).max() + 1e-12)) for k in range(0, len(bus), win)]
    print("windows above -2 dBFS:", [(round(t, 2), round(p, 1)) for t, p in hot if p > -2])
    for name, s in stems.items():
        pk = 20 * np.log10(np.abs(s).max() + 1e-12)
        print(f"  stem {name:12s} peak {pk:6.1f} dBFS")
    return i_lufs, tp


if __name__ == "__main__":
    report(json.loads(Path(sys.argv[1]).read_text()), sys.argv[2] if len(sys.argv) > 2 else None)
