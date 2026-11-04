#!/bin/zsh
# Transcribe a video with whisper.cpp (Metal GPU) -> work/<name>.srt + work/<name>.json
# Usage: scripts/transcribe.sh input/clip.mov [language]   (language: sr, en, auto... default auto)
set -euo pipefail

ROOT="${0:A:h:h}"
VIDEO="$1"
LANG_CODE="${2:-auto}"
MODEL="$ROOT/models/ggml-large-v3-turbo-q5_0.bin"
NAME="${VIDEO:t:r}"
WAV="$ROOT/work/$NAME.wav"

ffmpeg -hide_banner -loglevel error -y -i "$VIDEO" -vn -ac 1 -ar 16000 -c:a pcm_s16le "$WAV"
whisper-cli -m "$MODEL" -l "$LANG_CODE" -f "$WAV" -osrt -oj -of "$ROOT/work/$NAME" -np
rm -f "$WAV"
echo "-> $ROOT/work/$NAME.srt"
echo "-> $ROOT/work/$NAME.json"
