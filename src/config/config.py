"""
author: Yagnik Poshiya
github: https://github.com/yagnikposhiya/eternal-agent
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _get_env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    if v is None:
        return default
    v = v.strip()
    return v if v else default


@dataclass(frozen=True)
class Settings:
    # LiveKit (used by LiveKit Agents runtime internally)
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str

    # Agent identity for dispatch
    agent_name: str = "eternal-agent"

    # Providers
    deepgram_api_key: str = ""
    openai_api_key: str = ""
    cartesia_api_key: str = ""
    bey_api_key: str = ""

    # Supabase
    supabase_url: str = ""
    supabase_service_role_key: str = ""

    # Model configs
    openai_model: str = "gpt-4.1-mini"
    deepgram_model: str = "flux-general-en"
    cartesia_model: str = "sonic-3"
    cartesia_voice_id: str = "794f9389-aac1-45b6-b726-9d9369183238"
    bey_avatar_id: str = ""

    # Optional tuning
    eager_eot_threshold: float = 0.4
    preemptive_generation: bool = True
    resume_false_interruption: bool = True
    false_interruption_timeout: float = 1.0

    @staticmethod
    def from_env() -> "Settings":
        return Settings(
            livekit_url=_get_env("LIVEKIT_URL", "") or "",
            livekit_api_key=_get_env("LIVEKIT_API_KEY", "") or "",
            livekit_api_secret=_get_env("LIVEKIT_API_SECRET", "") or "",
            agent_name=_get_env("AGENT_NAME", "eternal-agent") or "eternal-agent",
            deepgram_api_key=_get_env("DEEPGRAM_API_KEY", "") or "",
            openai_api_key=_get_env("OPENAI_API_KEY", "") or "",
            cartesia_api_key=_get_env("CARTESIA_API_KEY", "") or "",
            openai_model=_get_env("OPENAI_MODEL", "gpt-4.1-mini") or "gpt-4.1-mini",
            deepgram_model=_get_env("DEEPGRAM_MODEL", "flux-general-en") or "flux-general-en",
            cartesia_model=_get_env("CARTESIA_MODEL", "sonic-3") or "sonic-3",
            cartesia_voice_id=_get_env(
                "CARTESIA_VOICE_ID",
                "794f9389-aac1-45b6-b726-9d9369183238",
            )
            or "794f9389-aac1-45b6-b726-9d9369183238",
            bey_api_key=_get_env("BEY_API_KEY","") or "",
            bey_avatar_id=_get_env("BEY_AVATAR_ID","") or "",
            supabase_url=_get_env("SUPABASE_URL", "") or "",
            supabase_service_role_key=_get_env("SUPABASE_SERVICE_ROLE_KEY", "") or "",
            eager_eot_threshold=float(_get_env("EAGER_EOT_THRESHOLD", "0.4") or "0.4"),
            preemptive_generation=(_get_env("PREEMPTIVE_GENERATION", "true") or "true").lower()
            in ("1", "true", "yes", "y"),
            resume_false_interruption=(
                _get_env("RESUME_FALSE_INTERRUPTION", "true") or "true"
            ).lower()
            in ("1", "true", "yes", "y"),
            false_interruption_timeout=float(
                _get_env("FALSE_INTERRUPTION_TIMEOUT", "1.0") or "1.0"
            ),
        )

    def validate(self) -> None:
        missing = []
        for key, val in [
            ("LIVEKIT_URL", self.livekit_url),
            ("LIVEKIT_API_KEY", self.livekit_api_key),
            ("LIVEKIT_API_SECRET", self.livekit_api_secret),
            ("DEEPGRAM_API_KEY", self.deepgram_api_key),
            ("OPENAI_API_KEY", self.openai_api_key),
            ("CARTESIA_API_KEY", self.cartesia_api_key),
            ("BEY_API_KEY", self.bey_api_key),
            ("BEY_AVATAR_ID", self.bey_avatar_id),
            ("SUPABASE_URL", self.supabase_url),
            ("SUPABASE_SERVICE_ROLE_KEY", self.supabase_service_role_key),
        ]:
            if not val:
                missing.append(key)

        if missing:
            raise ValueError(
                "Missing required environment variables: " + ", ".join(missing)
            )
