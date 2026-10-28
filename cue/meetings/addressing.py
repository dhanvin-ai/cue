"""Addressing check: Cue stays silent unless the utterance is directed at it."""

import re
from datetime import datetime, timedelta, timezone

NAME = re.compile(r"(?<!\w)@?cue(?!\w)", re.IGNORECASE)
DIRECT = re.compile(
    r"\b(?:can|could|would|will|do|did|are|were)\s+you\b"
    r"|\byou\s+(?:think|know|see|have|recommend|remember)\b"
    r"|\bwhat\s+do\s+you\b",
    re.IGNORECASE,
)
FOLLOW_UP = re.compile(r"^(?:and|also|so|then|what about|how about|why|what else)\b",
                       re.IGNORECASE)


def _question(text: str) -> bool:
    return text.strip().endswith("?")


def is_addressed(text: str, *, agent_name: str = "Cue", pause_ms: int = 0,
                 holds_answer: bool = False, active_exchange: bool = False,
                 silent: bool = False) -> bool:
    if silent:
        return False
    if NAME.search(text) or DIRECT.search(text):
        return True
    if pause_ms >= 2000 and holds_answer and _question(text):
        return True
    if active_exchange and (_question(text) or FOLLOW_UP.search(text.strip())):
        return True
    return False


class Addressing:
    """Tracks the short follow-up window after Cue has answered a turn."""

    def __init__(self, *, agent_name: str = "Cue", window_seconds: int = 45,
                 silent: bool = False):
        self.agent_name = agent_name
        self.window = timedelta(seconds=window_seconds)
        self.silent = silent
        self.active_until: datetime | None = None

    def check(self, text: str, *, pause_ms: int = 0, holds_answer: bool = False,
              now: datetime | None = None) -> bool:
        moment = now or datetime.now(timezone.utc)
        active = self.active_until is not None and moment <= self.active_until
        addressed = is_addressed(
            text, agent_name=self.agent_name, pause_ms=pause_ms,
            holds_answer=holds_answer, active_exchange=active, silent=self.silent,
        )
        if addressed:
            self.active_until = moment + self.window
        elif not active:
            self.active_until = None
        return addressed
