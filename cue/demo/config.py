"""Demo service settings, read once from the environment. Secrets stay server-side."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

HOME = Path(os.environ.get("CUE_DEMO_HOME", Path.home() / ".cue-demo"))
ROOT = Path(__file__).resolve().parents[2]


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class DemoSettings:
    api_key: str = field(default_factory=lambda: os.environ.get("CUE_DEMO_API_KEY", ""))
    db_path: Path = field(default_factory=lambda: Path(os.environ.get("CUE_DEMO_DB", HOME / "demo.sqlite3")))
    # Google OAuth for Cue's own account (written by scripts/demo_google_auth.py).
    google_token_file: Path = field(default_factory=lambda: Path(os.environ.get("CUE_DEMO_GOOGLE_TOKEN_FILE", HOME / "google-oauth.json")))
    calendar_id: str = field(default_factory=lambda: os.environ.get("CUE_DEMO_CALENDAR_ID", "primary"))
    public_url: str = field(default_factory=lambda: os.environ.get("CUE_DEMO_PUBLIC_URL", "http://localhost:3000").rstrip("/"))
    # Where the bot connects back to this service.
    internal_ws_base: str = field(default_factory=lambda: os.environ.get("CUE_DEMO_INTERNAL_WS", "ws://127.0.0.1:8780"))
    # Bot
    bot_enabled: bool = field(default_factory=lambda: os.environ.get("CUE_DEMO_BOT", "1") != "0")
    bot_profile: Path = field(default_factory=lambda: Path(os.environ.get("CUE_FACE_PROFILE", Path.home() / ".cue-face-bot" / "chrome-profile")))
    bot_extra_args: tuple[str, ...] = field(default_factory=lambda: tuple(os.environ.get("CUE_DEMO_BOT_ARGS", "").split()))
    bot_auto_admit: int = field(default_factory=lambda: _int("CUE_DEMO_AUTO_ADMIT", 2))
    # Voice
    model: str = field(default_factory=lambda: os.environ.get("CUE_DEMO_MODEL", "claude-opus-5-5"))
    stt_model: str = field(default_factory=lambda: os.environ.get("CUE_DEMO_STT_MODEL", "base.en"))
    tts_dir: Path = field(default_factory=lambda: Path(os.environ.get("CUE_DEMO_TTS_DIR", HOME / "kokoro")))
    tts_voice: str = field(default_factory=lambda: os.environ.get("CUE_DEMO_TTS_VOICE", "af_heart"))
    # Limits
    session_minutes: int = field(default_factory=lambda: _int("CUE_DEMO_SESSION_MINUTES", 20))
    per_ip_per_hour: int = field(default_factory=lambda: _int("CUE_DEMO_PER_IP_PER_HOUR", 3))
    per_email_per_day: int = field(default_factory=lambda: _int("CUE_DEMO_PER_EMAIL_PER_DAY", 3))
    per_day_total: int = field(default_factory=lambda: _int("CUE_DEMO_PER_DAY", 40))
    max_schedule_days: int = field(default_factory=lambda: _int("CUE_DEMO_MAX_SCHEDULE_DAYS", 14))
    transcript_retention_days: int = field(default_factory=lambda: _int("CUE_DEMO_TRANSCRIPT_DAYS", 7))
    session_retention_days: int = field(default_factory=lambda: _int("CUE_DEMO_SESSION_DAYS", 30))

    @property
    def tts_model_file(self) -> Path:
        return self.tts_dir / "kokoro-v1.0.onnx"

    @property
    def tts_voices_file(self) -> Path:
        return self.tts_dir / "voices-v1.0.bin"

    def missing(self) -> list[str]:
        """What prevents creating real meetings at all."""
        problems = []
        if not self.api_key:
            problems.append("CUE_DEMO_API_KEY")
        if not self.google_token_file.is_file():
            problems.append("Google OAuth for Cue's account (run scripts/demo_google_auth.py)")
        return problems

    def voice_missing(self) -> list[str]:
        """What prevents Cue from hearing and talking (the meeting still works without it)."""
        problems = []
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            problems.append("ANTHROPIC_API_KEY")
        if not (self.tts_model_file.is_file() and self.tts_voices_file.is_file()):
            problems.append("Kokoro TTS model (run scripts/demo_fetch_models.py)")
        return problems


settings = DemoSettings()
