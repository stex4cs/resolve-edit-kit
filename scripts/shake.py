#!/usr/bin/env python3
"""Measure camera shake per frame, so edits only use steady parts of handheld shots.

For every analyzed frame: global camera motion (dx, dy, rotation) from tracked features,
then "jitter" = distance of the camera path from its smoothed version (handshake / bumps),
and "speed" = smoothed motion (pans, whips). Units are % of frame height per frame.

Usage:
    .venv/bin/python scripts/shake.py OUT_DIR clip1.MP4 [clip2.MP4 ...]   -> OUT_DIR/<clip>.json
    .venv/bin/python scripts/shake.py --windows OUT_DIR/<clip>.json 1.0     -> steady windows >= 1.0s
"""
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

H = 480          # analysis height (px)
FPS = 25         # analysis frame rate
SMOOTH = 0.4     # seconds; camera path smoothing window
JITTER_OK = 0.35 # % of frame height; above this a frame counts as shaky
SPEED_OK = 1.2   # % of frame height per frame; above this it's a whip/fast pan


def frames(path):
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height,codec_name,pix_fmt:stream_side_data=rotation", "-of", "json", str(path)],
                           capture_output=True, text=True, check=True)
    s = json.loads(probe.stdout)["streams"][0]
    # VideoToolbox can't decode H.264 4:2:2 (Panasonic LongGOP) and silently repeats frames -> software decode.
    hw = [] if (s.get("codec_name") == "h264" and "422" in s.get("pix_fmt", "")) else ["-hwaccel", "videotoolbox"]
    rot = next((abs(int(d.get("rotation", 0))) for d in s.get("side_data_list", []) if "rotation" in d), 0)
    w, h = (s["height"], s["width"]) if rot in (90, 270) else (s["width"], s["height"])
    out_w = round(w * H / h / 2) * 2
    cmd = ["ffmpeg", "-nostdin", "-v", "error", *hw, "-i", str(path),
           "-vf", f"fps={FPS},scale={out_w}:{H}:flags=fast_bilinear,format=gray", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = out_w * H
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        yield np.frombuffer(buf, np.uint8).reshape(H, out_w)
    proc.wait()


def motion(path):
    """Per frame: (dx, dy, droll, ok). ok=False where tracking failed (cuts, blur, blank frames)."""
    prev = None
    rows = []
    for img in frames(path):
        row = (0.0, 0.0, 0.0, False)
        if prev is not None:
            pts = cv2.goodFeaturesToTrack(prev, maxCorners=300, qualityLevel=0.01, minDistance=12)
            if pts is not None and len(pts) >= 20:
                nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev, img, pts, None, winSize=(21, 21), maxLevel=3)
                good0, good1 = pts[st == 1], nxt[st == 1]
                if len(good0) >= 20:
                    m, inl = cv2.estimateAffinePartial2D(good0, good1, method=cv2.RANSAC, ransacReprojThreshold=1.5)
                    if m is not None and inl.mean() > 0.5:
                        row = (m[0, 2], m[1, 2], np.degrees(np.arctan2(m[1, 0], m[0, 0])), True)
        rows.append(row)
        prev = img
    return np.array(rows, dtype=float) if rows else np.zeros((0, 4))


def analyze(path):
    """jitter = how much camera velocity deviates from its local average (hand shake, bumps);
    speed = local average velocity (pans/whips). Both in % of frame height per frame.
    Computed per continuous segment so cuts and tracking failures never leak into neighbours."""
    a = motion(path)
    n = len(a)
    jitter = np.full(n, 99.0)
    speed = np.full(n, 99.0)
    k = max(3, int(SMOOTH * FPS) | 1)
    ok = a[:, 3] > 0 if n else np.zeros(0, bool)
    i = 0
    while i < n:
        if not ok[i]:
            i += 1
            continue
        j = i
        while j < n and ok[j]:
            j += 1
        seg = a[i:j]
        v = seg[:, :2] / H * 100
        roll = seg[:, 2] * 0.5  # 1 degree of roll ~ 0.5% of height
        if len(v) >= 3:
            kk = min(k, len(v) | 1 if len(v) % 2 else len(v) - 1)
            kernel = np.ones(kk) / kk
            sm = np.stack([np.convolve(np.pad(v[:, c], kk // 2, mode="edge"), kernel, "valid") for c in range(2)], 1)
            sr = np.convolve(np.pad(roll, kk // 2, mode="edge"), kernel, "valid")
            jitter[i:j] = np.linalg.norm(v - sm, axis=1) + np.abs(roll - sr)
            speed[i:j] = np.linalg.norm(sm, axis=1)
        i = j
    return {"file": str(path), "fps": FPS,
            "jitter": np.round(jitter, 3).tolist(), "speed": np.round(speed, 3).tolist()}


def windows(data, min_len):
    """Steady windows: every frame under JITTER_OK and SPEED_OK, at least min_len seconds."""
    fps = data["fps"]
    ok = [j < JITTER_OK and s < SPEED_OK for j, s in zip(data["jitter"], data["speed"])]
    out, start = [], None
    for i, good in enumerate(ok + [False]):
        if good and start is None:
            start = i
        elif not good and start is not None:
            if (i - start) / fps >= min_len:
                seg_j = data["jitter"][start:i]
                seg_s = data["speed"][start:i]
                out.append({"in": round(start / fps, 2), "out": round(i / fps, 2),
                            "jitter": round(float(np.mean(seg_j)), 3), "speed": round(float(np.mean(seg_s)), 3)})
            start = None
    return out


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--windows":
        d = json.loads(Path(sys.argv[2]).read_text())
        print(json.dumps(windows(d, float(sys.argv[3]) if len(sys.argv) > 3 else 1.0), indent=1))
        sys.exit()
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in sys.argv[2:]:
        dst = out_dir / (Path(f).stem + ".json")
        if dst.exists():
            continue
        dst.write_text(json.dumps(analyze(f)))
        print("done", Path(f).name, flush=True)
