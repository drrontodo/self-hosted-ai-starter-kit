#!/usr/bin/env python3
"""Drain pending transcription jobs using the locally installed faster-whisper.

Runs on the Windows host (where the GPU and the data directory live), not in the
container. Schedule via Task Scheduler, or run manually after uploading a recording:

    set CPD_API_KEY=...
    python scripts/drain_whisper.py --base-url http://localhost:8340 --data-dir .\\data

Requires: pip install faster-whisper (already installed on the target server).
"""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path


def api(base: str, key: str, path: str, payload: dict | None = None) -> dict | list:
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"X-API-Key": key, "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8340")
    parser.add_argument("--data-dir", default="./data", help="host path of the app's data volume")
    parser.add_argument("--model", default="large-v3", help="faster-whisper model name")
    args = parser.parse_args()

    key = os.environ.get("CPD_API_KEY", "")
    if not key:
        print("Set CPD_API_KEY in the environment.", file=sys.stderr)
        return 1

    jobs = api(args.base_url, key, "/api/jobs?engine=whisper&status=pending")
    if not jobs:
        print("No pending whisper jobs.")
        return 0

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper is not installed (pip install faster-whisper).", file=sys.stderr)
        return 1

    model = WhisperModel(args.model, device="cuda", compute_type="float16")
    data_dir = Path(args.data_dir)

    for job in jobs:
        audio = data_dir / "audio" / job["payload"]["audio_file"]
        if not audio.exists():
            api(args.base_url, key, f"/api/jobs/{job['id']}/fail",
                {"error": f"audio file not found on host: {audio}"})
            print(f"job {job['id']}: audio missing ({audio})")
            continue
        print(f"job {job['id']}: transcribing {audio.name} …")
        segments, _info = model.transcribe(str(audio), vad_filter=True)
        transcript = "\n".join(seg.text.strip() for seg in segments)
        result = api(args.base_url, key, f"/api/jobs/{job['id']}/result", {"transcript": transcript})
        print(f"job {job['id']}: done -> {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
