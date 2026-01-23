"""
author: Yagnik Poshiya
github: https://github.com/yagnikposhiya/eternal-agent
"""

from __future__ import annotations

import json
import time
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("eternal-agent")

from livekit.agents import Agent, RunContext, ChatContext, function_tool, get_job_context

from src.database.supabase import DBError, SupabaseDB
from src.prompts.greetings import GREETING_INSTRUCTIONS
from src.prompts.system import SYSTEM_INSTRUCTIONS_TEMPLATE
from src.prompts.summary_instructions import SUMMARY_INSTRUCTIONS_TEMPLATE
from src.utils.utils import normalize_phone, iso_to_ist_iso, now_ist_iso, IST_TZ_NAME, IST, parse_iso, get_today_ist_str, get_booking_window_end_ist_str
from src.utils.analytics import SessionAnalytics

TODAY_IST_STR = get_today_ist_str()
BOOKING_WINDOW_END_IST_STR = get_booking_window_end_ist_str(window_days=15, inclusive=True)

SYSTEM_INSTRUCTIONS = (
    SYSTEM_INSTRUCTIONS_TEMPLATE
    .replace("{TODAY_IST_STR}", TODAY_IST_STR)
    .replace("{BOOKING_WINDOW_END_IST_STR}", BOOKING_WINDOW_END_IST_STR)
)

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

class EternalAgent(Agent):
    def __init__(self, db: SupabaseDB, session_id: str, summary_llm: Any, summary_model: str, analytics: SessionAnalytics) -> None:
        super().__init__(instructions=SYSTEM_INSTRUCTIONS)
        self._db = db
        self._session_id = session_id
        self._summary_llm = summary_llm
        self._summary_model = summary_model
        self._analytics = analytics
        self._contact_number: Optional[str] = None
        self._contact_name: Optional[str] = None

    async def on_enter(self):
        # Initial greeting
        self.session.generate_reply(
            instructions=GREETING_INSTRUCTIONS,
            allow_interruptions=False,
        )

    async def _emit_tool_event(
        self,
        tool: str,
        input_json: Dict[str, Any],
        output_json: Dict[str, Any],
        ok: bool,
        error_message: Optional[str],
    ) -> None:
        # 1) Write to DB
        await asyncio.to_thread(
            self._db.insert_tool_event,
            self._session_id,
            tool,
            input_json,
            output_json,
            ok,
            error_message,
        )

        # 2) Push to frontend via LiveKit data message
        # publish_data signature supports topic/payload :contentReference[oaicite:1]{index=1}
        room = get_job_context().room
        payload = {
            "type": "tool_event",
            "session_id": self._session_id,
            "tool": tool,
            "input": input_json,
            "output": output_json,
            "ok": ok,
            "error_message": error_message,
            "ts": _utc_now_iso(),
            "ts_local": now_ist_iso(),
            "tz": IST_TZ_NAME,
        }
        await room.local_participant.publish_data(
            json.dumps(payload).encode("utf-8"),
            topic="tool_events",
        )

    async def _generate_and_store_summary(self) -> Dict[str, Any]:
        t0 = time.time()

        messages = await asyncio.to_thread(self._db.list_call_messages, self._session_id, 80)
        appts = await asyncio.to_thread(self._db.list_appointments_by_session, self._session_id, 30)

        # Prepare compact inputs (avoid huge tokens)
        convo_lines = []
        for m in messages:
            role = m.get("role", "")
            content = (m.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                convo_lines.append(f"{role.upper()}: {content}")

        # Appointments; keep only relevant fields
        appt_items = []
        for a in appts:
            appt_items.append(
                {
                    "status": a.get("status"),
                    "start_at": iso_to_ist_iso(a["start_at"]) if a.get("start_at") else None,
                    "end_at": iso_to_ist_iso(a["end_at"]) if a.get("end_at") else None,
                    "title": a.get("title"),
                    "notes": a.get("notes"),
                    "appointment_id": a.get("id"),
                }
            )

        # Caller reference for summary
        caller_name = (self._contact_name or "").strip()
        caller_ref = caller_name if caller_name else "the caller"

        prompt = (
            SUMMARY_INSTRUCTIONS_TEMPLATE.replace("{caller_ref}", caller_ref)
            + "Conversation:\n"
            + "\n".join(convo_lines[-80:])
            + "\n\n"
            + "Appointments (IST times):\n"
            + json.dumps(appt_items, ensure_ascii=False)
        )

        chat_ctx = ChatContext().empty()
        chat_ctx.add_message(role="system", content="You produce strictly valid JSON, no extra text.")
        chat_ctx.add_message(role="user", content=prompt)

        # Stream response; collect delta.content
        parts: list[str] = []
        async with self._summary_llm.chat(chat_ctx=chat_ctx) as stream:
            async for chunk in stream:
                delta = getattr(chunk, "delta", None)  # delta is ChoiceDelta | None
                if not delta:
                    continue

                # ChoiceDelta.content contains the streamed text
                txt = getattr(delta, "content", None)
                if txt:
                    parts.append(txt)

        out = "".join(parts)

        # Parse JSON safely
        summary_json: Dict[str, Any] = {}
        try:
            summary_json = json.loads(out)
        except Exception:
            summary_json = {
                "summary_text": out.strip()[:4000],
                "booked_appointments": [],
                "preferences": {"timezone": IST_TZ_NAME, "time_preferences": [], "date_preferences": [], "other": []},
            }

        # Save to DB
        gen_ms = int((time.time() - t0) * 1000)
        await asyncio.to_thread(
            self._db.upsert_call_summary,
            self._session_id,
            summary_json.get("summary_text") or "",
            summary_json.get("booked_appointments") or [],
            summary_json.get("preferences") or {"timezone": IST_TZ_NAME},
            self._summary_model,
            gen_ms,
        )

        return {
            "type": "call_summary",
            "session_id": self._session_id,
            "summary_text": summary_json.get("summary_text") or "",
            "booked_appointments": summary_json.get("booked_appointments") or [],
            "preferences": summary_json.get("preferences") or {"timezone": IST_TZ_NAME},
            "ts": _utc_now_iso(),
            "ts_local": now_ist_iso(),
            "tz": IST_TZ_NAME,
        }


    # -------------------------
    # Tools
    # -------------------------

    @function_tool()
    async def identify_user(
        self,
        context: RunContext,
        contact_number: str,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Identify the user by phone number. Create the contact if missing.
        Args:
            contact_number: User phone number (digits as string).
            name: User name if provided.
        Returns:
            Contact record (contact_number, name).
        """
        tool = "identify_user"
        raw_cn = contact_number
        cn = normalize_phone(raw_cn)

        input_json = {"contact_number": raw_cn, "normalized_contact_number": cn, "name": name}

        try:
            row = await asyncio.to_thread(self._db.upsert_contact, cn, name)
            await asyncio.to_thread(self._db.set_session_contact, self._session_id, cn)

            self._contact_number = cn
            self._contact_name = row.get("name")

            output_json = {"contact_number": row["contact_number"], "name": row.get("name")}
            await self._emit_tool_event(tool, input_json, output_json, True, None)
            return output_json
        except Exception as e:
            msg = str(e)
            await self._emit_tool_event(tool, input_json, {"error": msg}, False, msg)
            return {"error": msg}

    @function_tool()
    async def fetch_slots(
        self,
        context: RunContext,
        start_date_utc_iso: Optional[str] = None,
        days: int = 7,
    ) -> Dict[str, Any]:
        """Fetch available slots for booking.
        Args:
            start_date_utc_iso: ISO datetime in UTC to start searching from. If omitted, uses now (UTC).
            days: How many days forward to list slots (default 7).
        Returns:
            List of slots with availability.
        """
        tool = "fetch_slots"
        input_json = {"start_date_utc_iso": start_date_utc_iso, "days": days}

        try:
            start_local = datetime.now(IST) if not start_date_utc_iso else parse_iso(start_date_utc_iso).astimezone(IST)
            end_local = start_local + timedelta(days=max(1, min(days, 14)))

            start_iso = start_local.astimezone(timezone.utc).isoformat()
            end_iso = end_local.astimezone(timezone.utc).isoformat()

            slots = await asyncio.to_thread(self._db.list_slots, start_iso, end_iso)
            booked_ids = set(await asyncio.to_thread(self._db.booked_slot_ids, start_iso, end_iso))

            out_slots = []
            for s in slots:
                sid = str(s["id"])
                start_utc = s["start_at"]
                end_utc = s["end_at"]
                out_slots.append(
                    {
                        "slot_id": sid,
                        "start_at": iso_to_ist_iso(start_utc),
                        "end_at": iso_to_ist_iso(end_utc),
                        "start_at_utc": start_utc,
                        "end_at_utc": end_utc,
                        "timezone": IST_TZ_NAME,
                        "available": sid not in booked_ids,
                    }
                )

            output_json = {"slots": out_slots}
            await self._emit_tool_event(tool, input_json, output_json, True, None)
            return output_json
        except Exception as e:
            msg = str(e)
            await self._emit_tool_event(tool, input_json, {"error": msg}, False, msg)
            return {"error": msg}

    @function_tool()
    async def book_appointment(
        self,
        context: RunContext,
        slot_id: str,
        title: Optional[str] = None,
        notes: Optional[str] = None,
        contact_number: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Book an appointment for a user in a given slot.
        Args:
            slot_id: The slot UUID to book.
            title: Short title (optional).
            notes: Notes (optional).
            contact_number: Phone number; if omitted uses previously identified user.
        Returns:
            Appointment record.
        """
        tool = "book_appointment"

        raw_cn = (contact_number or self._contact_number or "").strip()
        cn = normalize_phone(raw_cn) if raw_cn else ""
        input_json = {
            "slot_id": slot_id,
            "title": title,
            "notes": notes,
            "contact_number": contact_number,
            "resolved_contact_number": raw_cn,
            "normalized_contact_number": cn,
        }

        try:
            if not raw_cn:
                raise DBError("Missing contact_number. Call identify_user first.")

            appt = await asyncio.to_thread(
                self._db.book_appointment,
                cn,
                slot_id,
                title,
                notes,
                self._session_id,
            )
            output_json = {
                "appointment_id": appt["id"],
                "contact_number": appt["contact_number"],
                "slot_id": appt["slot_id"],
                "start_at": iso_to_ist_iso(appt["start_at"]),
                "end_at": iso_to_ist_iso(appt["end_at"]),
                "start_at_utc": appt["start_at"],
                "end_at_utc": appt["end_at"],
                "timezone": IST_TZ_NAME,
                "status": appt["status"],
                "title": appt.get("title"),
            }
            await self._emit_tool_event(tool, input_json, output_json, True, None)
            return output_json
        except Exception as e:
            msg = str(e)
            # Typical double-book error will land here; LLM can recover by fetching slots again.
            await self._emit_tool_event(tool, input_json, {"error": msg}, False, msg)
            return {"error": msg}

    @function_tool()
    async def retrieve_appointments(
        self,
        context: RunContext,
        contact_number: Optional[str] = None,
        include_cancelled: bool = False,
        limit: int = 5,
    ) -> Dict[str, Any]:
        """Retrieve appointments for a user.
        Args:
            contact_number: Phone number; if omitted uses previously identified user.
            include_cancelled: Include cancelled appointments.
            limit: Max number of appointments.
        Returns:
            List of appointments.
        """
        tool = "retrieve_appointments"

        raw_cn = (contact_number or self._contact_number or "").strip()
        cn = normalize_phone(raw_cn)

        input_json = {
            "contact_number": contact_number,
            "resolved_contact_number": raw_cn,
            "normalized_contact_number": cn,
            "include_cancelled": include_cancelled,
            "limit": limit,
        }

        try:
            if not raw_cn:
                raise DBError("Missing contact_number. Call identify_user first.")

            rows_raw = await asyncio.to_thread(
                self._db.list_appointments,
                cn,
                include_cancelled,
                max(1, min(limit, 20))
            )

            rows = []
            for r in rows_raw:
                start_utc = r.get("start_at")
                end_utc = r.get("end_at")
                rows.append(
                    {
                        **r,
                        "start_at": iso_to_ist_iso(start_utc) if start_utc else start_utc,
                        "end_at": iso_to_ist_iso(end_utc) if end_utc else end_utc,
                        "start_at_utc": start_utc,
                        "end_at_utc": end_utc,
                        "timezone": IST_TZ_NAME,
                    }
                )
            
            output_json = {"appointments": rows}
            await self._emit_tool_event(tool, input_json, output_json, True, None)
            return output_json
        except Exception as e:
            msg = str(e)
            await self._emit_tool_event(tool, input_json, {"error": msg}, False, msg)
            return {"error": msg}

    @function_tool()
    async def cancel_appointment(
        self,
        context: RunContext,
        appointment_id: str,
    ) -> Dict[str, Any]:
        """Cancel an existing appointment by appointment_id."""
        tool = "cancel_appointment"
        input_json = {"appointment_id": appointment_id}

        try:
            row = await asyncio.to_thread(self._db.cancel_appointment, appointment_id)
            cancelled_utc = row.get("cancelled_at")

            output_json = {
                "appointment_id": row["id"],
                "status": row["status"],

                # Cancel time (both UTC + IST)
                "cancelled_at": iso_to_ist_iso(cancelled_utc) if cancelled_utc else None,
                "cancelled_at_utc": cancelled_utc,
                "timezone": IST_TZ_NAME,
            }
            await self._emit_tool_event(tool, input_json, output_json, True, None)
            return output_json
        except Exception as e:
            msg = str(e)
            await self._emit_tool_event(tool, input_json, {"error": msg}, False, msg)
            return {"error": msg}

    @function_tool()
    async def modify_appointment(
        self,
        context: RunContext,
        appointment_id: str,
        new_slot_id: str,
    ) -> Dict[str, Any]:
        """Modify an existing appointment to a new slot."""
        tool = "modify_appointment"
        input_json = {"appointment_id": appointment_id, "new_slot_id": new_slot_id}

        try:
            row = await asyncio.to_thread(self._db.modify_appointment, appointment_id, new_slot_id)
            output_json = {
                "appointment_id": row["id"],
                "slot_id": row["slot_id"],

                "start_at": iso_to_ist_iso(row["start_at"]),
                "end_at": iso_to_ist_iso(row["end_at"]),
                "start_at_utc": row["start_at"],
                "end_at_utc": row["end_at"],
                "timezone": IST_TZ_NAME,

                "status": row["status"],
            }
            await self._emit_tool_event(tool, input_json, output_json, True, None)
            return output_json
        except Exception as e:
            msg = str(e)
            await self._emit_tool_event(tool, input_json, {"error": msg}, False, msg)
            return {"error": msg}

    @function_tool()
    async def end_conversation(
        self,
        context: RunContext,
    ) -> Dict[str, Any]:
        """End the conversation/call."""
        tool = "end_conversation"
        input_json = {}

        try:
            try:
                summary_payload = await asyncio.wait_for(
                    self._generate_and_store_summary(),
                    timeout=200.0,
                )
            except asyncio.TimeoutError:
                logger.warning("Summary generation timed out")
                summary_payload = {
                    "type": "call_summary",
                    "session_id": self._session_id,
                    "summary_text": "Summary is not available right now.",
                    "booked_appointments": [],
                    "preferences": {"timezone": IST_TZ_NAME, "time_preferences": [], "date_preferences": [], "other": []},
                    "ts": _utc_now_iso(),
                    "ts_local": now_ist_iso(),
                    "tz": IST_TZ_NAME,
                }

                # IMPORTANT: store fallback too, so DB is never empty
                await asyncio.to_thread(
                    self._db.upsert_call_summary,
                    self._session_id,
                    summary_payload["summary_text"],
                    summary_payload["booked_appointments"],
                    summary_payload["preferences"],
                    self._summary_model,
                    None,
                )
            except Exception:
                logger.exception("Summary generation failed")
                # Same fallback + store
                summary_payload = {
                    "type": "call_summary",
                    "session_id": self._session_id,
                    "summary_text": "Summary is not available right now.",
                    "booked_appointments": [],
                    "preferences": {"timezone": IST_TZ_NAME, "time_preferences": [], "date_preferences": [], "other": []},
                    "ts": _utc_now_iso(),
                    "ts_local": now_ist_iso(),
                    "tz": IST_TZ_NAME,
                }
                await asyncio.to_thread(
                    self._db.upsert_call_summary,
                    self._session_id,
                    summary_payload["summary_text"],
                    summary_payload["booked_appointments"],
                    summary_payload["preferences"],
                    self._summary_model,
                    None,
                )

            try:
                # Try to extract metrics from UsageCollector if available
                session = getattr(self, "session", None)
                if session and hasattr(session, "userdata"):
                    usage_collector = session.userdata.get("usage")
                    if usage_collector and hasattr(usage_collector, "get_summary"):
                        try:
                            usage_summary = usage_collector.get_summary()
                            if usage_summary:
                                self._analytics.ingest_usage_summary(usage_summary)
                        except Exception:
                            logger.exception("Failed to ingest usage summary")
                
                summary_payload["session_analytics"] = self._analytics.report()
            except Exception:
                logger.exception("Failed to attach session analytics")

            # Publish summary
            room = get_job_context().room
            await room.local_participant.publish_data(
                json.dumps(summary_payload).encode("utf-8"),
                topic="call_summary",
            )

            # (optional safety) give the data packet a moment before shutdown
            await asyncio.sleep(0.2)

            await asyncio.to_thread(self._db.end_call_session, self._session_id)

            output_json = {"session_id": self._session_id, "ended_at": _utc_now_iso()}
            await self._emit_tool_event(tool, input_json, output_json, True, None)

            self.session.shutdown(drain=True)
            return output_json

        except Exception as e:
            msg = str(e)
            await self._emit_tool_event(tool, input_json, {"error": msg}, False, msg)
            return {"error": msg}

