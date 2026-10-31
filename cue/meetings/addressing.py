"""Addressing check: Cue stays silent unless the utterance is directed at it."""

import re
from datetime import datetime, timedelta, timezone

DIRECT = re.compile(
    r"\b(?:can|could|would|will|do|did|are|were)\s+you\b"
    r"|\byou\s+(?:think|know|see|have|recommend|remember)\b"
    r"|\bwhat\s+do\s+you\b",
    re.IGNORECASE,
)
FOLLOW_UP = re.compile(r"^(?:and|also|so|then|what about|how about|why|what else)\b",
                       re.IGNORECASE)


# Live captions often mishear a one-syllable name; accept the usual sound-alikes, but only as
# the first word and followed by a comma or a question/request word, so "the job queue is
# stuck" or "queue is backed up" never wakes Cue.
SOUND_ALIKES = {"cue": r"q|queue|kew|kyu|eq|que|cu"}
ASKING = (r"are|what|what's|who|where|when|why|how|can|could|did|will|would|should|tell|show"
          r"|give|summarize|find|check|remind|hi|hello|hey")
# Any of these greetings can open a request ("Hey / Hello / Hi / Okay Cue").
GREETINGS = r"uh|um|hey|hi|hello|ok|okay|so|and"
# Transcribers sometimes fuse a greeting with a short name: "HiQ", "OKQ".
FUSED = {"cue": re.compile(r"\s*(?:hey|hi|hello|ok|okay)q\b", re.IGNORECASE)}


def _mentions(text: str, agent_name: str) -> bool:
    if re.search(rf"(?<!\w)@?{re.escape(agent_name)}(?!\w)", text, re.IGNORECASE):
        return True
    alikes = SOUND_ALIKES.get(agent_name.lower())
    if not alikes:
        return False
    fused = FUSED.get(agent_name.lower())
    if fused and fused.match(text):
        return True
    return bool(re.match(
        rf"\s*(?:(?:{GREETINGS})[,.\s]+)*(?:{alikes})(?:\s*[,.!?]|\s+(?:{ASKING})\b)",
        text, re.IGNORECASE))


def _question(text: str) -> bool:
    return text.strip().endswith("?")


def is_addressed(text: str, *, agent_name: str = "Cue", pause_ms: int = 0,
                 holds_answer: bool = False, active_exchange: bool = False,
                 silent: bool = False) -> bool:
    if silent:
        return False
    if _mentions(text, agent_name) or DIRECT.search(text):
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
