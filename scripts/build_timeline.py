#!/usr/bin/env python3
"""Build a DaVinci Resolve timeline (.otio + .fcpxml) from a JSON edit plan.

The timeline references the ORIGINAL media files (no re-encode), so color
grading in Resolve works on full-quality footage.

Usage:
    .venv/bin/python scripts/build_timeline.py plans/my_edit.json

Plan format (times in seconds or "HH:MM:SS.mmm", relative to clip start):
    {
      "name": "MojaMontaza",
      "fps": 25,                       # optional, defaults to first clip's fps
      "clips": [
        {"file": "input/A001.mov", "in": 12.5, "out": 18.0},
        {"file": "input/A002.mov", "in": "00:01:03.200", "out": "00:01:07.000"}
      ]
    }

Multi-track format (tracks listed bottom-up; "at" = timeline position in seconds,
otherwise the clip follows the previous one on its track):
    {
      "name": "Promo", "fps": 25,
      "tracks": [
        {"name": "V1", "kind": "video", "clips": [{"file": ..., "in": 0, "out": 2}, ...]},
        {"name": "A1", "kind": "audio", "clips": [{"file": ..., "in": 26.7, "out": 43.6, "at": 1.0}]},
        {"name": "A2", "kind": "audio", "clips": [{"file": "music.wav", "in": 10, "out": 55}]}
      ]
    }
"""
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import opentimelineio as otio

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "timelines"


def parse_time(value):
    if isinstance(value, (int, float)):
        return float(value)
    seconds = 0.0
    for part in str(value).split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True,
    )
    info = json.loads(out.stdout)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    fps = float(Fraction(video["r_frame_rate"])) if video else None
    duration = float(info["format"]["duration"])
    timecode = (video or {}).get("tags", {}).get("timecode") or info["format"].get("tags", {}).get("timecode")
    return fps, duration, timecode, has_audio


def timecode_to_seconds(tc, fps):
    if not tc:
        return 0.0
    h, m, s, f = (int(x) for x in tc.replace(";", ":").split(":"))
    return h * 3600 + m * 60 + s + f / round(fps)


def resolve_path(file):
    path = Path(file) if Path(file).is_absolute() else (ROOT / file).resolve()
    if not path.exists():
        sys.exit(f"Missing media: {path}")
    return path


def normalize(plan):
    """Return [(name, kind, clips)]; the simple 'clips' format becomes V1 + A1 from the same clips."""
    if "tracks" in plan:
        return [(t.get("name", t["kind"][0].upper() + str(i)), t["kind"], t["clips"])
                for i, t in enumerate(plan["tracks"], 1)]
    return [("V1", "video", plan["clips"]), ("A1", "audio", plan["clips"])]


def main(plan_path):
    plan_path = Path(plan_path)
    plan = json.loads(plan_path.read_text())
    name = plan.get("name", plan_path.stem)
    tracks = normalize(plan)

    probes = {}
    for _, _, clips in tracks:
        for c in clips:
            c["_path"] = resolve_path(c["file"])
            if c["_path"] not in probes:
                probes[c["_path"]] = probe(c["_path"])

    first = tracks[0][2][0]["_path"]
    fps = plan.get("fps") or probes[first][0]
    rt = lambda sec, rate=fps: otio.opentime.RationalTime(round(sec * rate), rate)

    timeline = otio.schema.Timeline(name=name, global_start_time=otio.opentime.RationalTime(0, fps))
    summary = []
    for track_name, kind, clips in tracks:
        is_video = kind == "video"
        track = otio.schema.Track(
            name=track_name, kind=otio.schema.TrackKind.Video if is_video else otio.schema.TrackKind.Audio)
        timeline.tracks.append(track)
        cursor = 0  # timeline frames
        for i, c in enumerate(clips, 1):
            path = c["_path"]
            src_fps, duration, tc, has_audio = probes[path]
            if is_video and src_fps is None:
                sys.exit(f"{track_name} clip {i} ({path.name}) has no video")
            if not is_video and not has_audio:
                track.append(otio.schema.Gap(source_range=otio.opentime.TimeRange(duration=rt(
                    parse_time(c["out"]) - parse_time(c["in"])))))
                cursor = round(track.duration().to_seconds() * fps)
                continue
            rate = src_fps or fps
            tc_start = timecode_to_seconds(tc, rate)
            t_in, t_out = parse_time(c["in"]), parse_time(c["out"])
            if not 0 <= t_in < t_out <= duration + 0.01:
                sys.exit(f"{track_name} clip {i} ({path.name}): bad range {t_in}-{t_out}, media is {duration:.2f}s")

            if "at" in c:
                at = round(parse_time(c["at"]) * fps)
                if at < cursor:
                    sys.exit(f"{track_name} clip {i} ({path.name}) at {c['at']} overlaps previous clip")
                if at > cursor:
                    track.append(otio.schema.Gap(source_range=otio.opentime.TimeRange(
                        duration=otio.opentime.RationalTime(at - cursor, fps))))
                    cursor = at

            # Length is quantized to whole timeline frames so clips butt together exactly.
            frames = round((t_out - t_in) * fps)
            start = rt(tc_start + t_in, rate)
            length = otio.opentime.RationalTime(frames, fps).rescaled_to(rate)
            ref = otio.schema.ExternalReference(
                target_url=path.as_uri(),
                available_range=otio.opentime.TimeRange(rt(tc_start, rate), rt(duration, rate)),
            )
            track.append(otio.schema.Clip(
                name=c.get("name", path.stem), media_reference=ref,
                source_range=otio.opentime.TimeRange(start, length)))
            cursor += frames
        summary.append(f"{track_name}: {len(clips)} clips, ends {cursor / fps:.2f}s")

    OUT_DIR.mkdir(exist_ok=True)
    written = []
    for ext in ("otio", "fcpxml"):
        out = OUT_DIR / f"{name}.{ext}"
        otio.adapters.write_to_file(timeline, str(out))
        written.append(out)

    print(f"{name} @ {fps:g}fps, {timeline.duration().to_seconds():.2f}s")
    for line in summary:
        print("  " + line)
    for out in written:
        print(f"  -> {out}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
