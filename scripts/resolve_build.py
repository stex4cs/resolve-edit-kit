#!/usr/bin/env python3
"""Build a timeline directly inside a running DaVinci Resolve Studio from a JSON plan.

Unlike build_timeline.py (OTIO/FCPXML files), this drives the Resolve API, so it also
sets per-clip rotation/zoom, speed (optical flow), audio volume, voice isolation and
markers. Media is referenced in place (no copies, no re-encode).

Usage:
    .venv/bin/python scripts/resolve_build.py plans/my_edit.json

Plan:
    {
      "project": "MyProject",              # loaded, or created with the settings below
      "timeline": "MyEdit_v1",             # existing name -> "_2", "_3"... is appended
      "fps": 25, "width": 1080, "height": 1920,
      "bin": "MyEdit",                     # media pool folder for imported media
      "tracks": [                          # bottom-up; kind video|audio
        {"name": "V1", "kind": "video", "clips": [
          {"file": "/path/clip.MP4", "in": 2.0, "out": 3.5, "at": 0.0,
           "speed": 50, "props": {"RotationAngle": 90, "ZoomX": 1.778, "ZoomY": 1.778},
           "stabilize": true, "note": "why this shot"}]},
        {"name": "VO", "kind": "audio", "voice_isolation": 60, "clips": [
          {"file": "/path/clip.MP4", "in": 26.7, "out": 43.7, "at": 0.8, "volume": 4}]}
      ],
      "markers": [{"at": 18.0, "color": "Red", "name": "Drop"}]
    }

Times are seconds. "in"/"out" are the source range that should be SEEN; with "speed"
below 100 the clip occupies (out-in)*100/speed seconds on the timeline. "at" defaults
to the end of the previous clip on the same track.

More per-clip keys: "retime" (nearest|frame_blend|optical_flow), "dynamic_zoom": true
(push-in), "composite" (overlay|screen|...), "opacity", "fade_in"/"fade_out" (seconds),
"super_scale": 2 (media pool item), "transition_in": {"type": "Zoom In", "category":
"fusion", "duration": 8, "alignment": "center"} (on the clip's head).
Track key "look": true puts its video clips into plan["look"]["group"], a color group
whose post-clip node gets plan["look"]["lut"] — clip nodes stay free for grading.
"""
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
os.environ.setdefault("RESOLVE_SCRIPT_API", API)
os.environ.setdefault(
    "RESOLVE_SCRIPT_LIB",
    "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
)
sys.path.append(f"{API}/Modules")


def frame(seconds, fps):
    """Round half up (Python's round() is banker's rounding: round(12.5) == 12)."""
    return math.floor(seconds * fps + 0.5)


def media_path(file):
    path = Path(file) if Path(file).is_absolute() else ROOT / file
    if not path.exists():
        sys.exit(f"Missing media: {path}")
    return str(path.resolve())


def open_project(resolve, plan):
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if not project or project.GetName() != plan["project"]:
        project = pm.LoadProject(plan["project"])
    if not project:
        project = pm.CreateProject(plan["project"])
        for key, value in (("timelineResolutionWidth", plan.get("width", 1920)),
                           ("timelineResolutionHeight", plan.get("height", 1080)),
                           ("timelineFrameRate", plan.get("fps", 25))):
            project.SetSetting(key, str(value))
    if not project:
        sys.exit(f"Cannot open or create project {plan['project']}")
    return project


def import_media(media_pool, bin_name, paths):
    root = media_pool.GetRootFolder()
    folder = next((f for f in root.GetSubFolderList() if f.GetName() == bin_name), None) \
        or media_pool.AddSubFolder(root, bin_name)
    media_pool.SetCurrentFolder(folder)
    known = {c.GetClipProperty("File Path"): c for c in folder.GetClipList() or []}
    missing = [p for p in paths if p not in known]
    if missing:
        print(f"importing {len(missing)} files (first import of long HEVC files can take a while)...")
        for item in media_pool.ImportMedia(missing) or []:
            known[item.GetClipProperty("File Path")] = item
    lost = [p for p in paths if p not in known]
    if lost:
        sys.exit("Resolve did not import: " + ", ".join(lost))
    return known


def unique_timeline_name(project, name):
    existing = {project.GetTimelineByIndex(i).GetName() for i in range(1, project.GetTimelineCount() + 1)}
    candidate, n = name, 2
    while candidate in existing:
        candidate, n = f"{name}_{n}", n + 1
    return candidate


def main(plan_path, resolve=None):
    """resolve: pass the `resolve` object when running inside Resolve (Workspace > Scripts);
    otherwise connect over external scripting."""
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    if resolve is None:
        import DaVinciResolveScript as dvr
        resolve = dvr.scriptapp("Resolve")
    if not resolve:
        sys.exit("Resolve is not running or External scripting is not set to Local.")
    project = open_project(resolve, plan)
    media_pool = project.GetMediaPool()
    fps = float(project.GetSetting("timelineFrameRate"))

    paths = sorted({media_path(c["file"]) for t in plan["tracks"] for c in t["clips"]})
    items = import_media(media_pool, plan.get("bin", plan["timeline"]), paths)

    name = unique_timeline_name(project, plan["timeline"])
    timeline = media_pool.CreateEmptyTimeline(name)
    project.SetCurrentTimeline(timeline)
    start = timeline.GetStartFrame()

    counters = {"video": 0, "audio": 0}
    pending_transitions, look_items = [], []
    for track in plan["tracks"]:
        kind = track["kind"]
        counters[kind] += 1
        index = counters[kind]
        while timeline.GetTrackCount(kind) < index:
            timeline.AddTrack(kind, "stereo") if kind == "audio" else timeline.AddTrack(kind)
        timeline.SetTrackName(kind, index, track.get("name", f"{kind[0].upper()}{index}"))
        if "voice_isolation" in track:
            timeline.SetVoiceIsolationState(index, {"isEnabled": True, "amount": int(track["voice_isolation"])})

        cursor = 0.0
        for c in track["clips"]:
            mpi = items[media_path(c["file"])]
            if c.get("super_scale") and str(mpi.GetClipProperty("Super Scale")) != str(c["super_scale"]):
                mpi.SetClipProperty("Super Scale", int(c["super_scale"]))
            src_fps = float(mpi.GetClipProperty("FPS") or fps)
            speed = float(c.get("speed", 100))
            seen = c["out"] - c["in"]
            at = c.get("at", cursor)
            # Both edges from absolute times, so half-frame lengths (0.5s at 25fps) never leave gaps.
            at_frame = frame(at, fps)
            tl_frames = frame(at + seen * 100 / speed, fps) - at_frame
            # Resolve keeps the item length on SetSpeed, so append the source span that fills
            # the wanted timeline length at 100% and change the speed afterwards.
            src_start = round(c["in"] * src_fps)
            src_end = src_start + round(tl_frames / fps * src_fps)
            appended = media_pool.AppendToTimeline([{
                "mediaPoolItem": mpi, "startFrame": src_start, "endFrame": src_end,
                "mediaType": 1 if kind == "video" else 2,
                "trackIndex": index, "recordFrame": start + at_frame,
            }])
            if not appended:
                sys.exit(f"{track.get('name')}: could not place {Path(c['file']).name} at {at}s "
                         f"(source {src_start}-{src_end} of {mpi.GetClipProperty('Frames')} frames)")
            item = appended[0]
            if speed != 100:
                item.SetSpeed({"Percentage": speed, "RippleTimeline": False})
                retime = c.get("retime", "optical_flow" if speed < 100 else "frame_blend")
                item.SetProperty("RetimeProcess", getattr(resolve, "RETIME_" + retime.upper()))
            for key, value in c.get("props", {}).items():
                item.SetProperty(key, value)
            if c.get("dynamic_zoom"):
                item.SetProperty("DynamicZoomEnabled", True)
                item.SetProperty("DynamicZoomEase", resolve.DYNAMIC_ZOOM_EASE_IN_AND_OUT)
            if c.get("composite"):
                item.SetProperty("CompositeMode", getattr(resolve, "COMPOSITE_" + c["composite"].upper()))
            if "opacity" in c:
                item.SetProperty("Opacity", float(c["opacity"]))
            if "volume" in c:
                item.SetProperty("AudioVolume", float(c["volume"]))
            if c.get("fade_in") or c.get("fade_out"):
                if not item.SetFades({"FadeIn": frame(c.get("fade_in", 0), fps), "FadeOut": frame(c.get("fade_out", 0), fps)}):
                    print(f"  warning: fades not set on {Path(c['file']).name} at {at}s")
            if c.get("stabilize") and not item.Stabilize():
                print(f"  warning: stabilization failed for {Path(c['file']).name} at {at}s")
            if c.get("color"):
                item.SetClipColor(c["color"])
            if c.get("transition_in"):
                pending_transitions.append((item, c["transition_in"], f"{track.get('name')} @{at}s"))
            if kind == "video" and track.get("look") and c.get("look", True):
                look_items.append(item)
            cursor = (at_frame + tl_frames) / fps

    # Transitions need both neighbours in place, so they go in after all clips.
    for item, tr, where in pending_transitions:
        ok = None
        for alignment in (tr.get("alignment", "center"), "right", "left"):
            for dur in (tr.get("duration", 10), 6, 4):
                ok = item.AddTransition({"type": tr["type"], "category": tr.get("category", "simple"),
                                         "position": "start", "alignment": alignment, "duration": dur})
                if ok:
                    break
            if ok:
                break
        if not ok:
            print(f"  warning: transition {tr['type']} failed at {where}")
        elif (alignment, dur) != (tr.get("alignment", "center"), tr.get("duration", 10)):
            print(f"  note: {tr['type']} at {where} placed as {alignment}/{dur}f")

    look = plan.get("look")
    if look and look_items:
        group = next((g for g in project.GetColorGroupsList() or [] if g.GetName() == look["group"]), None) \
            or project.AddColorGroup(look["group"])
        for item in look_items:
            item.AssignToColorGroup(group)
        project.RefreshLUTList()
        if not group.GetPostClipNodeGraph().SetLUT(1, look["lut"]):
            print(f"  warning: could not set look LUT {look['lut']}")

    for m in plan.get("markers", []):
        timeline.AddMarker(frame(m["at"], fps), m.get("color", "Blue"), m.get("name", ""), m.get("note", ""), 1)

    # Smooth playback: smart render cache + cached color output for every picture clip
    # (4K 10-bit HEVC + stabilization + Super Scale is not real-time; uncached playback crackles).
    for key, value in (("perfRenderCacheMode", "smart"), ("perfAutoRenderCacheEnable", "1"),
                       ("perfAutoRenderCacheTransition", "1"), ("perfAutoRenderCacheComposite", "1")):
        project.SetSetting(key, value)
    for item in timeline.GetItemListInTrack("video", 1) or []:
        if item.GetType() != "transition":
            item.SetColorOutputCache(True)

    resolve.OpenPage("edit")
    clips_only = lambda k, t: [it for it in timeline.GetItemListInTrack(k, t) or [] if it.GetType() != "transition"]
    end = max((it.GetEnd() for k in ("video", "audio") for t in range(1, timeline.GetTrackCount(k) + 1)
               for it in clips_only(k, t)), default=start)
    print(f"{project.GetName()} / {name}: {(end - start) / fps:.2f}s")
    for k in ("video", "audio"):
        for t in range(1, timeline.GetTrackCount(k) + 1):
            n_tr = len(timeline.GetItemListInTrack(k, t) or []) - len(clips_only(k, t))
            print(f"  {k} {t} {timeline.GetTrackName(k, t)}: {len(clips_only(k, t))} clips"
                  + (f", {n_tr} transitions" if n_tr else ""))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
