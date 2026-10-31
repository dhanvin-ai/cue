"""Download the self-hosted speech models the Meet CUE demo uses (one time, ~0.5 GB).

Kokoro-82M (Apache-2.0) ONNX weights and voices for TTS, and the faster-whisper model for
speech-to-text, into CUE_DEMO_HOME (default ~/.cue-demo). Nothing is committed to the repo.

    .venv/bin/python scripts/demo_fetch_models.py
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cue.demo.config import settings  # noqa: E402

KOKORO = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"


def fetch(url: str, target: Path) -> None:
    if target.is_file() and target.stat().st_size > 0:
        print(f"ok   {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    print(f"get  {url}")
    with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
    partial.rename(target)
    print(f"ok   {target} ({target.stat().st_size // (1 << 20)} MB)")


def main() -> None:
    fetch(KOKORO + "kokoro-v1.0.onnx", settings.tts_model_file)
    fetch(KOKORO + "voices-v1.0.bin", settings.tts_voices_file)
    from faster_whisper import WhisperModel

    print(f"get  faster-whisper {settings.stt_model}")
    WhisperModel(settings.stt_model, device="cpu", compute_type="int8")
    print(f"ok   faster-whisper {settings.stt_model}")


if __name__ == "__main__":
    main()
