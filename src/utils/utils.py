"""
author: Yagnik Poshiya
github: https://github.com/yagnikposhiya/eternal-agent
"""

from __future__ import annotations

import re

from typing import Union
from livekit.agents import JobProcess
from livekit.plugins import silero
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

IST = timezone(timedelta(hours=5, minutes=30))
IST_TZ = ZoneInfo("Asia/Kolkata")
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

def get_today_ist_date() -> date:
    """
    Returns today's date in IST as a datetime.date object.
    Example print format: 2026-01-23
    """
    return datetime.now(IST_TZ).date()


def get_today_ist_str() -> str:
    """
    Returns today's date string in the format used by your system instructions.
    Format: '23 Jan 2026 (Friday)'
    """
    now_ist = datetime.now(IST_TZ)
    return now_ist.strftime("%d %b %Y (%A)")


def get_booking_window_end_ist_date(window_days: int = 14, inclusive: bool = True) -> date:
    """
    Returns the booking window end date in IST as a datetime.date object.

    - window_days=15 means a 15-day window starting from today.
    - inclusive=True: end date = today + (window_days - 1)
      Example: today + 14 => total 15 days including today.
    - inclusive=False: end date = today + window_days
      Example: today + 15 (often used when end is exclusive)
    """
    today = get_today_ist_date()
    delta_days = (window_days - 1) if inclusive else window_days
    return today + timedelta(days=delta_days)


def get_booking_window_end_ist_str(window_days: int = 14, inclusive: bool = True) -> str:
    """
    Returns the booking window end date string.
    Format: '22 Feb 2026'
    """
    end_date = get_booking_window_end_ist_date(window_days=window_days, inclusive=inclusive)
    return end_date.strftime("%d %b %Y")