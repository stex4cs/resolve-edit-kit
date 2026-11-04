#!/usr/bin/env python3
"""Music structure for cutting: beat grid, per-bar energy (all / kick / hats), drops, and bar-join checks.

Usage:
  .venv/bin/python scripts/music_analyze.py SONG [--bpm 116]                 # bar table + biggest jumps
  .venv/bin/python scripts/music_analyze.py SONG --bpm 116 --join 14:61 69:79  # chroma similarity of jumps
       (A:B = leave the song at the start of bar A, continue from the start of bar B; 2.0 = identical, >=1.8 seamless)
Use --bpm with the tempo Artlist reports (detected tempo can be off by a few BPM).
Bars are counted from the detected beat phase: bar i starts at phase + i * 240/BPM.
"""
import sys, subprocess
import numpy as np
import librosa
from scipy.signal import butter, sosfilt


def load(path, sr=22050):
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.float32).astype(np.float64), sr


def main(a):
    y, sr = load(a[0])
    bpm = float(a[a.index("--bpm") + 1]) if "--bpm" in a else float(np.atleast_1d(librosa.beat.beat_track(y=y, sr=sr, start_bpm=120)[0])[0])
    beat, bar = 60 / bpm, 240 / bpm
    on = librosa.onset.onset_strength(y=y, sr=sr, hop_length=256)
    t = librosa.frames_to_time(np.arange(len(on)), sr=sr, hop_length=256)
    ph = max(np.arange(0, beat, 0.005), key=lambda p: np.interp(np.arange(p, t[-1], beat), t, on).sum())
    n = int((len(y) / sr - ph) / bar)
    lo = sosfilt(butter(4, 120, "lp", fs=sr, output="sos"), y); hi = sosfilt(butter(4, 6000, "hp", fs=sr, output="sos"), y)
    db = lambda x, i: 20 * np.log10(np.sqrt(np.mean(x[int((ph + i * bar) * sr):int((ph + (i + 1) * bar) * sr)] ** 2)) + 1e-9)
    rows = [(i, ph + i * bar, db(y, i), db(lo, i), db(hi, i)) for i in range(n)]
    print(f"{a[0]}: {bpm:.1f} BPM, beat {beat:.4f}s, bar {bar:.4f}s, phase {ph:.3f}s, {n} bars, length {len(y)/sr:.2f}s")
    if "--join" not in a:
        for r in rows:
            print(f"  bar {r[0]:3d} @{r[1]:7.2f}s  all {r[2]:6.1f}  kick {r[3]:6.1f}  hats {r[4]:6.1f}")
        j = np.diff([r[2] for r in rows]); top = np.argsort(j)[-4:][::-1]
        print("biggest level jumps (drop candidates):", ", ".join(f"bar {i+1} @{ph+(i+1)*bar:.2f}s (+{j[i]:.1f} dB)" for i in top))
        return
    C = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=512); tc = librosa.frames_to_time(np.arange(C.shape[1]), sr=sr, hop_length=512)
    def v(i):
        m = (tc >= ph + i * bar) & (tc < ph + (i + 1) * bar); x = C[:, m].mean(1); return x / (np.linalg.norm(x) + 1e-9)
    for spec in a[a.index("--join") + 1:]:
        if spec.startswith("--"): break
        A, B = map(int, spec.split(":"))
        sim = v(A - 1) @ v(B - 1) + v(A) @ v(B)
        print(f"  leave at bar {A} ({ph+A*bar:.2f}s) -> continue at bar {B} ({ph+B*bar:.2f}s): similarity {sim:.3f} "
              f"{'OK' if sim >= 1.8 else 'AUDIBLE - pick other bars'} | level {rows[A-1][2]:.1f} -> {rows[B][2]:.1f} dB")


if __name__ == "__main__":
    main(sys.argv[1:])
