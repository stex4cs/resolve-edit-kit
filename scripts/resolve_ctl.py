#!/usr/bin/env python3
"""Control a running DaVinci Resolve Studio from the terminal.

Usage (.venv/bin/python scripts/resolve_ctl.py <command> ...):
    status                          product, project, timelines
    project NAME                    load project NAME (create it if missing)
    import [FILE]                   import timeline (.otio/.fcpxml/.edl) with its media;
                                    default: newest .otio in timelines/
    lut LUT_PATH [--node N]         apply LUT to every video clip of the current timeline
    cdl [--slope "R G B"] [--offset "R G B"] [--power "R G B"] [--sat S] [--node N]
                                    set CDL on every video clip of the current timeline
    still OUT.png                   export the current Color-page frame (with grade) as image
    presets                         list render presets
    render [--preset P] [--out DIR] [--name NAME] [--format mp4 --codec H264 --quality 40000]
                                    render the current timeline and wait until done

Requires Resolve to be running and Preferences > System > General >
External scripting using = Local.
"""
import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
os.environ.setdefault("RESOLVE_SCRIPT_API", API)
os.environ.setdefault(
    "RESOLVE_SCRIPT_LIB",
    "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
)
sys.path.append(f"{API}/Modules")

import DaVinciResolveScript as dvr  # noqa: E402


def connect():
    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        sys.exit("Resolve is not running, or Preferences > General > External scripting is not set to 'Local'.")
    return resolve


def current(resolve):
    project = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline() if project else None
    return project, timeline


def video_items(timeline):
    items = []
    for track in range(1, timeline.GetTrackCount("video") + 1):
        items += timeline.GetItemListInTrack("video", track) or []
    return items


def require_timeline(resolve):
    project, timeline = current(resolve)
    if not timeline:
        sys.exit("No active timeline.")
    return project, timeline


def cmd_status(resolve, args):
    project, timeline = current(resolve)
    print(resolve.GetProductName(), resolve.GetVersionString(), "| page:", resolve.GetCurrentPage())
    if not project:
        return
    print("project:", project.GetName())
    for i in range(1, project.GetTimelineCount() + 1):
        tl = project.GetTimelineByIndex(i)
        mark = "*" if timeline and tl.GetUniqueId() == timeline.GetUniqueId() else " "
        print(f" {mark} timeline: {tl.GetName()} ({len(video_items(tl))} clips)")


def cmd_project(resolve, args):
    pm = resolve.GetProjectManager()
    project = pm.LoadProject(args.name) or pm.CreateProject(args.name)
    if not project:
        sys.exit(f"Ne mogu da otvorim/napravim projekat {args.name}")
    print("project:", project.GetName())


def cmd_import(resolve, args):
    if args.file:
        path = Path(args.file).resolve()
    else:
        candidates = sorted((ROOT / "timelines").glob("*.otio"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            sys.exit("No .otio file in timelines/")
        path = candidates[-1]
    project, _ = current(resolve)
    timeline = project.GetMediaPool().ImportTimelineFromFile(str(path), {"importSourceClips": True})
    if not timeline:
        sys.exit(f"Import failed: {path}")
    project.SetCurrentTimeline(timeline)
    resolve.OpenPage("edit")
    print(f"imported: {timeline.GetName()} ({len(video_items(timeline))} clips) <- {path}")


def cmd_lut(resolve, args):
    _, timeline = require_timeline(resolve)
    lut = str(Path(args.lut).resolve())
    ok = [item.GetNodeGraph().SetLUT(args.node, lut) for item in video_items(timeline)]
    print(f"LUT on {sum(ok)}/{len(ok)} clips (node {args.node})")


def cmd_cdl(resolve, args):
    _, timeline = require_timeline(resolve)
    cdl = {"NodeIndex": args.node, "Slope": args.slope, "Offset": args.offset,
           "Power": args.power, "Saturation": args.sat}
    ok = [item.SetCDL(cdl) for item in video_items(timeline)]
    print(f"CDL on {sum(ok)}/{len(ok)} clips: {cdl}")


def cmd_still(resolve, args):
    project, _ = require_timeline(resolve)
    resolve.OpenPage("color")
    out = str(Path(args.out).resolve())
    if not project.ExportCurrentFrameAsStill(out):
        sys.exit("Still export failed")
    print("still:", out)


def cmd_presets(resolve, args):
    project, _ = current(resolve)
    print("\n".join(project.GetRenderPresetList()))


def cmd_render(resolve, args):
    project, timeline = require_timeline(resolve)
    if args.preset and not project.LoadRenderPreset(args.preset):
        sys.exit(f"Nepoznat preset: {args.preset} (vidi 'presets')")
    if args.format:
        if not project.SetCurrentRenderFormatAndCodec(args.format, args.codec or "H264"):
            sys.exit(f"Nepoznat format/kodek: {args.format}/{args.codec}")
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    settings = {
        "SelectAllFrames": True,
        "TargetDir": str(out_dir),
        "CustomName": args.name or timeline.GetName(),
        "FormatWidth": int(timeline.GetSetting("timelineResolutionWidth")),
        "FormatHeight": int(timeline.GetSetting("timelineResolutionHeight")),
    }
    if args.quality:
        settings["VideoQuality"] = int(args.quality) if str(args.quality).isdigit() else args.quality
    if not project.SetRenderSettings(settings):
        print("warning: some render settings were rejected")
    job = project.AddRenderJob()
    if not job or not project.StartRendering([job]):
        sys.exit("Render did not start")
    while project.IsRenderingInProgress():
        status = project.GetRenderJobStatus(job)
        print(f"\r{status.get('CompletionPercentage', 0)}%", end="", flush=True)
        time.sleep(2)
    status = project.GetRenderJobStatus(job)
    print(f"\r{status.get('JobStatus')} -> {out_dir}")
    project.DeleteRenderJob(job)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("project").add_argument("name")
    sub.add_parser("import").add_argument("file", nargs="?")
    p = sub.add_parser("lut")
    p.add_argument("lut")
    p.add_argument("--node", type=int, default=1)
    p = sub.add_parser("cdl")
    p.add_argument("--slope", default="1 1 1")
    p.add_argument("--offset", default="0 0 0")
    p.add_argument("--power", default="1 1 1")
    p.add_argument("--sat", type=float, default=1.0)
    p.add_argument("--node", type=int, default=1)
    sub.add_parser("still").add_argument("out")
    sub.add_parser("presets")
    p = sub.add_parser("render")
    p.add_argument("--preset")
    p.add_argument("--out", default=str(ROOT / "output"))
    p.add_argument("--name")
    p.add_argument("--format", help="mp4 | mov (see Project.GetRenderFormats)")
    p.add_argument("--codec", help="H264 | H265 | ProRes422HQ | ...")
    p.add_argument("--quality", help="kbps (e.g. 40000) or Least/Low/Medium/High/Best")

    args = parser.parse_args()
    globals()[f"cmd_{args.cmd}"](connect(), args)


if __name__ == "__main__":
    main()
