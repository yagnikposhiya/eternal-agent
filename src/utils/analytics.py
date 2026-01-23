"""
author: Yagnik Poshiya
github: https://github.com/yagnikposhiya/eternal-agent
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from datetime import datetime, timezone

def _get(obj: Any, key: str, default: Any = 0) -> Any:
    """Safe getter for dicts or objects."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)

def _norm_metric_type(v: Any) -> str:
    """
    Normalize LiveKit metric type to a lowercase string.
    LiveKit SDKs may expose this as:
    - plain string: "llm"
    - enum-like: MetricType.LLM with `.value`
    - repr: "MetricType.llm" / "LLM"
    """
    if v is None:
        return ""
    vv = getattr(v, "value", None)
    if isinstance(vv, str):
        return vv.strip().lower()
    s = str(v).strip().lower()
    # common enum-ish representations
    if "." in s:
        s = s.split(".")[-1]
    return s

def _first_int(*vals: Any, default: int = 0) -> int:
    for v in vals:
        if v is None:
            continue
        try:
            iv = int(v)
        except Exception:
            continue
        return iv
    return default

@dataclass
class PricingUSD:
    # You can move these to env later
    openai_in_per_million: float = 0.40
    openai_out_per_million: float = 1.60

    deepgram_per_min: float = 0.0077

    cartesia_per_100k_chars: float = 5.0

    # $49 for 140 agent minutes => per minute:
    bey_per_min: float = 49.0 / 140.0

@dataclass
class UsageTotals:
    # LLM
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0

    # STT
    stt_audio_ms: int = 0  # audio duration

    # TTS
    tts_chars: int = 0

    # Session duration (for bey)
    session_ms: int = 0

@dataclass
class SessionAnalytics:
    pricing: PricingUSD = field(default_factory=PricingUSD)

    started_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at_utc: Optional[datetime] = None

    usage: UsageTotals = field(default_factory=UsageTotals)

    # ---------- ingestion ----------
    def ingest_metrics(self, metrics_input: Any) -> None:
        """
        Ingest LiveKit AgentMetrics.
        Can be a single metric object (STTMetrics, LLMMetrics, TTSMetrics) or a list.
        """
        if not metrics_input:
            return
        
        # Handle both list and single metric object
        metrics_list = metrics_input if isinstance(metrics_input, (list, tuple)) else [metrics_input]
        
        for m in metrics_list:
            if m is None:
                continue
            
            # Detect metric type from class name (e.g., STTMetrics -> "stt", LLMMetrics -> "llm")
            class_name = m.__class__.__name__.lower()
            mtype = ""
            if "stt" in class_name:
                mtype = "stt"
            elif "llm" in class_name:
                mtype = "llm"
            elif "tts" in class_name:
                mtype = "tts"
            else:
                # Fallback: try to get type attribute
                mtype = _norm_metric_type(_get(m, "type", None))
            
            # Get duration - try multiple field names and handle seconds->ms conversion
            dur_ms = 0
            dur_sec = _get(m, "duration", None)
            dur_ms_attr = _get(m, "duration_ms", None)
            
            if dur_ms_attr is not None:
                try:
                    dur_ms = int(float(dur_ms_attr))
                except (ValueError, TypeError):
                    pass
            elif dur_sec is not None:
                try:
                    dur_ms = int(float(dur_sec) * 1000)  # Convert seconds to ms
                except (ValueError, TypeError):
                    pass

            if mtype == "llm":
                usage = _get(m, "usage", None)
                # Try multiple ways to get tokens
                self.usage.llm_input_tokens += _first_int(
                    _get(usage, "input_tokens", None) if usage else None,
                    _get(usage, "prompt_tokens", None) if usage else None,
                    _get(m, "input_tokens", None),
                    _get(m, "prompt_tokens", None),
                    default=0,
                )
                self.usage.llm_output_tokens += _first_int(
                    _get(usage, "output_tokens", None) if usage else None,
                    _get(usage, "completion_tokens", None) if usage else None,
                    _get(m, "output_tokens", None),
                    _get(m, "completion_tokens", None),
                    default=0,
                )

            elif mtype == "stt":
                # audio_duration is the length of audio processed (for usage/cost), in seconds
                audio_dur_sec = _get(m, "audio_duration", None)
                audio_dur_ms = 0
                if audio_dur_sec is not None:
                    try:
                        audio_dur_ms = int(float(audio_dur_sec) * 1000)  # Convert seconds to ms
                    except (ValueError, TypeError):
                        pass
                else:
                    # Fallback to ms attributes
                    audio_dur_ms = _first_int(
                        _get(m, "audio_duration_ms", None),
                        _get(m, "audio_ms", None),
                        default=0,
                    )
                self.usage.stt_audio_ms += audio_dur_ms

            elif mtype == "tts":
                self.usage.tts_chars += _first_int(
                    _get(m, "characters_count", None),
                    _get(m, "character_count", None),
                    _get(m, "chars", None),
                    default=0,
                )

    def ingest_usage_summary(self, summary: Dict[str, Any]) -> None:
        """
        Ingest data from LiveKit UsageCollector.get_summary().
        This is a fallback when metrics_collected events don't fire or have different structure.
        """
        if not summary or not isinstance(summary, dict):
            return
        
        import logging
        logger = logging.getLogger("eternal-agent")
        logger.info(f"[USAGE_SUMMARY] Ingesting summary: {summary}")
        
        # UsageCollector summary typically has structure like:
        # {
        #   "llm": {"input_tokens": X, "output_tokens": Y, "duration_ms": Z},
        #   "stt": {"audio_duration_ms": X, "duration_ms": Y},
        #   "tts": {"characters_count": X, "duration_ms": Y},
        # }
        
        llm_data = summary.get("llm", {})
        if llm_data:
            logger.debug(f"[USAGE_SUMMARY] LLM data: {llm_data}")
            self.usage.llm_input_tokens += _first_int(
                llm_data.get("input_tokens"),
                llm_data.get("prompt_tokens"),
                default=0,
            )
            self.usage.llm_output_tokens += _first_int(
                llm_data.get("output_tokens"),
                llm_data.get("completion_tokens"),
                default=0,
            )
        
        stt_data = summary.get("stt", {})
        if stt_data:
            logger.debug(f"[USAGE_SUMMARY] STT data: {stt_data}")
            self.usage.stt_audio_ms += _first_int(
                stt_data.get("audio_duration_ms"),
                stt_data.get("audio_ms"),
                # audio_duration might be in seconds
                int(float(stt_data.get("audio_duration", 0)) * 1000) if stt_data.get("audio_duration") else 0,
                default=0,
            )
        
        tts_data = summary.get("tts", {})
        if tts_data:
            logger.debug(f"[USAGE_SUMMARY] TTS data: {tts_data}")
            self.usage.tts_chars += _first_int(
                tts_data.get("characters_count"),
                tts_data.get("character_count"),
                tts_data.get("chars"),
                default=0,
            )

    def end(self) -> None:
        if self.ended_at_utc is None:
            self.ended_at_utc = datetime.now(timezone.utc)
        delta_ms = int((self.ended_at_utc - self.started_at_utc).total_seconds() * 1000)
        self.usage.session_ms = max(0, delta_ms)

    # ---------- reporting ----------
    def compute_cost_usd(self) -> Dict[str, Any]:
        p = self.pricing
        u = self.usage

        openai = (u.llm_input_tokens / 1_000_000.0) * p.openai_in_per_million + \
                 (u.llm_output_tokens / 1_000_000.0) * p.openai_out_per_million

        deepgram = (u.stt_audio_ms / 60000.0) * p.deepgram_per_min
        cartesia = (u.tts_chars / 100_000.0) * p.cartesia_per_100k_chars
        bey = (u.session_ms / 60000.0) * p.bey_per_min

        total = openai + deepgram + cartesia + bey

        return {
            "total_usd": round(total, 6),
            "breakdown_usd": {
                "openai": round(openai, 6),
                "deepgram": round(deepgram, 6),
                "cartesia": round(cartesia, 6),
                "bey": round(bey, 6),
            },
            "usage": {
                "llm_input_tokens": u.llm_input_tokens,
                "llm_output_tokens": u.llm_output_tokens,
                "stt_audio_minutes": round(u.stt_audio_ms / 60000.0, 4),
                "tts_characters": u.tts_chars,
                "session_minutes": round(u.session_ms / 60000.0, 4),
            },
        }

    def report(self) -> Dict[str, Any]:
        self.end()
        return {
            "cost": self.compute_cost_usd(),
        }
