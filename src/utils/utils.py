"""
author: Yagnik Poshiya
github: https://github.com/yagnikposhiya/eternal-agent
"""

from __future__ import annotations

import re

from typing import Union
from livekit.agents import JobProcess
from livekit.plugins import silero
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
IST_TZ_NAME = "Asia/Kolkata"

def prewarm(proc: JobProcess) -> None:
    """
    Preload heavy resources once per worker process.
    """
    proc.userdata["vad"] = silero.VAD.load()

def normalize_phone(raw: str) -> str:
    """
    Normalize phone number to 10-digit Indian format when possible.
    - Removes spaces, +, -, etc.
    - Converts 91XXXXXXXXXX -> XXXXXXXXXX
    """
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    return d

def parse_iso(value: Union[str, datetime]) -> datetime:
    """Parse ISO string safely. Supports trailing Z, and assumes UTC if tz missing."""
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    v = (value or "").replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def iso_to_ist_iso(value: str) -> str:
    """Convert an ISO datetime string to IST ISO string (+05:30)."""
    return parse_iso(value).astimezone(IST).isoformat()

def now_ist_iso() -> str:
    """Current time in IST as ISO string."""
    return datetime.now(IST).isoformat()