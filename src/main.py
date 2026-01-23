"""
author: Yagnik Poshiya
github: https://github.com/yagnikposhiya/eternal-agent
"""

from __future__ import annotations

import os
import asyncio
import logging

from dotenv import load_dotenv
from livekit.plugins import cartesia, deepgram, openai, silero, bey
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livekit.agents import AgentServer, AgentSession, JobContext, JobProcess, cli, metrics, ConversationItemAddedEvent

from src.agent.eternal import EternalAgent
from src.config.config import Settings
from src.database.supabase import SupabaseDB
from src.utils.analytics import SessionAnalytics

logger = logging.getLogger("eternal-agent")
logging.basicConfig(level=logging.INFO)

load_dotenv()
SETTINGS = Settings.from_env()
SETTINGS.validate()

AGENT_NAME = SETTINGS.agent_name

server = AgentServer()


def setup_process(proc: JobProcess):
    # Prewarm heavy resources once per worker process
    proc.userdata["vad"] = silero.VAD.load()
    proc.userdata["db"] = SupabaseDB.from_env(SETTINGS.supabase_url, SETTINGS.supabase_service_role_key)


server.setup_fnc = setup_process


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext):
    
    await ctx.connect()
    ctx.log_context_fields = {"room": ctx.room.name}

    db: SupabaseDB = ctx.proc.userdata["db"]
    session_id = await asyncio.to_thread(db.create_call_session, ctx.room.name)

    session = AgentSession(
        stt=deepgram.STTv2(
            model=SETTINGS.deepgram_model,
            eager_eot_threshold=SETTINGS.eager_eot_threshold,
        ),
        llm=openai.LLM(model=SETTINGS.openai_model),
        tts=cartesia.TTS(
            model=SETTINGS.cartesia_model,
            voice=SETTINGS.cartesia_voice_id,
        ),
        vad=ctx.proc.userdata["vad"],
        turn_detection=MultilingualModel(),
        preemptive_generation=SETTINGS.preemptive_generation,
        resume_false_interruption=SETTINGS.resume_false_interruption,
        false_interruption_timeout=SETTINGS.false_interruption_timeout,
    )

    analytics = SessionAnalytics()
    usage = metrics.UsageCollector()
    session.userdata = {"analytics": analytics, "usage": usage}

    @session.on("metrics_collected")
    def _on_metrics(ev):
        metrics.log_metrics(ev.metrics)
        usage.collect(ev.metrics)

        try:
            raw_metrics = getattr(ev, "metrics", ev)
            if raw_metrics:
                class_name = raw_metrics.__class__.__name__
                logger.info(f"[METRICS] Received metrics: {class_name}")
                # Log ALL non-private attributes for debugging
                all_attrs = [x for x in dir(raw_metrics) if not x.startswith('_')]
                logger.info(f"[METRICS] {class_name} available attributes: {all_attrs}")
                # Log key attributes with their values
                attrs_to_check = ["duration", "duration_ms", "audio_duration", "audio_duration_ms", 
                                 "input_tokens", "output_tokens", "characters_count", "character_count",
                                 "usage", "type"]
                for attr in attrs_to_check:
                    if hasattr(raw_metrics, attr):
                        try:
                            val = getattr(raw_metrics, attr)
                            logger.info(f"[METRICS] {class_name}.{attr} = {val} (type: {type(val).__name__})")
                        except Exception as e:
                            logger.debug(f"[METRICS] Could not read {class_name}.{attr}: {e}")
            analytics.ingest_metrics(raw_metrics)
        except Exception:
            logger.exception("Failed to ingest metrics")

    async def _store_message(role: str, text: str, meta: dict):
        t = (text or "").strip()
        if not t:
            return
        try:
            await asyncio.to_thread(db.insert_call_message, session_id, role, t, meta)
        except Exception:
            logger.exception("Failed to insert call_message")
        
    def _fire_and_log(task: asyncio.Task):
        def _done(t: asyncio.Task):
            try:
                t.result()
            except Exception:
                logger.exception("Background task failed")
        task.add_done_callback(_done)

    @session.on("conversation_item_added")
    def _on_conversation_item_added(ev: ConversationItemAddedEvent):
        try:
            item = getattr(ev, "item", None)
            if not item:
                return

            role = getattr(item, "role", None) or "unknown"

            # Defensive across LiveKit versions
            text = (
                getattr(item, "text_content", None)
                or getattr(item, "text", None)
                or getattr(item, "content", None)
                or ""
            )

            # If content is a list of segments (sometimes happens), extract text parts
            if isinstance(text, list):
                parts = []
                for seg in text:
                    seg_text = getattr(seg, "text", None) or (seg.get("text") if isinstance(seg, dict) else None)
                    if seg_text:
                        parts.append(seg_text)
                text = "".join(parts)

            text = (text or "").strip()
            if not text:
                return

            task = asyncio.create_task(
                _store_message(role, text, {"event": "conversation_item_added"})
            )
            _fire_and_log(task)

        except Exception:
            logger.exception("conversation_item_added handler failed")

    async def _log_usage():
        summary = usage.get_summary()
        logger.info("Usage summary: %s", summary)
        try:
            analytics.ingest_usage_summary(summary)
        except Exception:
            logger.exception("Failed to ingest usage summary into analytics")

    ctx.add_shutdown_callback(_log_usage)

    avatar = bey.AvatarSession(
        api_key=SETTINGS.bey_api_key,
        avatar_id=SETTINGS.bey_avatar_id,
        avatar_participant_identity="Eternal (SuperBryn)",
        avatar_participant_name="Eternal (SuperBryn)",
    )
    await avatar.start(session, room=ctx.room)

    agent = EternalAgent(
        db=db, 
        session_id=session_id, 
        summary_llm=openai.LLM(model=SETTINGS.openai_model), 
        summary_model=SETTINGS.openai_model,
        analytics=analytics
        )
    await session.start(room=ctx.room, agent=agent)


if __name__ == "__main__":
    cli.run_app(server)
