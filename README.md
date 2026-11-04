# resolve-edit-kit

Scripts I use to cut event videos in DaVinci Resolve Studio from the terminal.

The edit lives in a JSON file: which clips, which part of each clip, where it sits on the timeline, how fast it plays. One command turns that file into a real Resolve timeline that points at the original camera files, so colour grading still happens on full-quality footage. The other scripts answer the questions that come up before and after the cut: which part of a handheld shot is steady enough to use, where the bars of the song are, and whether the render is loud enough without clipping.

Built on macOS with Resolve Studio 21. Nothing is re-encoded unless you ask for a preview render.

## What's here

| Script | What it does |
| --- | --- |
| `resolve_build.py` | JSON plan → timeline inside a running Resolve: tracks, clip ranges, speed and retiming, zoom/rotation, stabilisation, fades, transitions, voice isolation, markers |
| `build_timeline.py` | Same plan → `.otio` and `.fcpxml` files, for when Resolve isn't running or for other editors |
| `resolve_ctl.py` | Drive Resolve from the shell: load a project, import a timeline, apply a LUT or CDL to every clip, export a graded still, render with a preset |
| `shake.py` | Measures camera shake per frame (feature tracking + smoothed camera path) and lists the steady windows in each clip |
| `windows.py` | Turns `shake.py` output into two lists per clip: steady shots, and smooth intentional moves (pans, slides, drone) |
| `music_analyze.py` | Beat grid, energy per bar, drops, and a check for whether two bars of a song can be joined without an audible jump |
| `mix_sim.py` | Simulates the plan's audio mix offline and reports integrated loudness and true peak before you render |
| `qa_render.py` | Checks a finished render against its plan: loudness, shake per shot, 4 fps contact sheets, frames around every transition |
| `contact.py`, `sheet.py` | Contact strips for picking exact frames |
| `crackle.py` | Finds clicks and crackle in an audio track |
| `transcribe.sh` | Local transcription with whisper.cpp (Metal) → `.srt` + `.json` |
| `rmcp.py` | Calls a tool of the MCP server that ships with Resolve, from the command line |

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
brew install ffmpeg whisper-cpp   # whisper only for transcribe.sh
```

In Resolve: **Preferences → General → External scripting using → Local**. External scripting needs Resolve **Studio**. The scripts look for the scripting API in the default macOS install path; set `RESOLVE_SCRIPT_API` and `RESOLVE_SCRIPT_LIB` if yours is elsewhere.

Expected folders next to `scripts/`: `input/` (camera files, never modified), `plans/`, `timelines/`, `work/`, `output/`.

## A plan

```json
{
  "project": "EventRecap",
  "timeline": "Recap_v1",
  "fps": 25, "width": 1080, "height": 1920,
  "tracks": [
    {"name": "V1", "kind": "video", "clips": [
      {"file": "input/drone_01.MP4", "in": 4.0, "out": 7.0, "at": 0.0},
      {"file": "input/crowd_03.MP4", "in": 2.0, "out": 3.5, "speed": 50, "retime": "optical_flow", "stabilize": true}
    ]},
    {"name": "VO", "kind": "audio", "voice_isolation": 60, "clips": [
      {"file": "input/interview.MP4", "in": 26.7, "out": 33.7, "at": 0.8, "volume": 4}
    ]}
  ],
  "markers": [{"at": 6.0, "color": "Red", "name": "Drop"}]
}
```

`in`/`out` is the part of the source you want to *see*. At `speed` 50 that 1.5 s range takes 3 s on the timeline. `at` defaults to the end of the previous clip on the same track. The full list of keys is in the docstring of `resolve_build.py`; two complete examples are in `plans/`.

```bash
.venv/bin/python scripts/resolve_build.py plans/example-resolve.json
```

## A typical pass

```bash
# 1. which parts of the handheld footage are usable
.venv/bin/python scripts/shake.py work/shake input/*.MP4
.venv/bin/python scripts/windows.py work/shake work/windows.json --min 0.8

# 2. where the song's bars and drops are
.venv/bin/python scripts/music_analyze.py input/track.wav --bpm 116

# 3. write plans/recap.json, build it, check the mix before rendering
.venv/bin/python scripts/resolve_build.py plans/recap.json
.venv/bin/python scripts/mix_sim.py plans/recap.json

# 4. render a preview and QA it
.venv/bin/python scripts/resolve_ctl.py render --preset "H.264 Master" --name recap
.venv/bin/python scripts/qa_render.py plans/recap.json output/recap.mov work/qa
```

The loudness target I aim for on social video is around −14 LUFS integrated with true peak under −1 dBTP.

## Notes

Some comments in the code are in Serbian; the interfaces and messages are in English. These are working tools, not a library: they do what my edits needed and nothing more. Issues and pull requests are welcome.

## License

MIT
