"""
author: Yagnik Poshiya
github: https://github.com/yagnikposhiya/eternal-agent
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Optional
from supabase import Client, create_client
from src.utils.utils import normalize_phone

class DBError(RuntimeError):
    pass

def _unwrap(resp: Any) -> Tuple[Any, Any]:
    data = getattr(resp, "data", None)
    err = getattr(resp, "error", None)
    return data, err

@dataclass
class SupabaseDB:
    client: Client

    @staticmethod
    def from_env(supabase_url: str, service_role_key: str) -> "SupabaseDB":
        if not supabase_url or not service_role_key:
            raise DBError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        return SupabaseDB(client=create_client(supabase_url, service_role_key))

    # -------------------------
    # Core entities
    # -------------------------
    def create_call_session(self, room_name: str) -> str:
        resp = (
            self.client.table("call_sessions")
            .insert({"room_name": room_name, "status": "active"})
            .execute()
        )
        data, err = _unwrap(resp)
        if err:
            raise DBError(str(err))
        return str(data[0]["id"])

    def set_session_contact(self, session_id: str, contact_number: str) -> None:
        contact_number = normalize_phone(contact_number)
        resp = (
            self.client.table("call_sessions")
            .update({"contact_number": contact_number})
            .eq("id", session_id)
            .execute()
        )
        _, err = _unwrap(resp)
        if err:
            raise DBError(str(err))

    def end_call_session(self, session_id: str) -> None:
        resp = (
            self.client.table("call_sessions")
            .update({"status": "ended", "ended_at": "now()"})
            .eq("id", session_id)
            .execute()
        )
        _, err = _unwrap(resp)
        if err:
            raise DBError(str(err))

    def upsert_contact(self, contact_number: str, name: Optional[str]) -> Dict[str, Any]:
        contact_number = normalize_phone(contact_number)
        payload: Dict[str, Any] = {"contact_number": contact_number}
        if name:
            payload["name"] = name

        resp = (
            self.client.table("contacts")
            .upsert(payload, on_conflict="contact_number")
            .execute()
        )
        data, err = _unwrap(resp)
        if err:
            raise DBError(str(err))
        return data[0]

    # -------------------------
    # Slots / availability
    # -------------------------
    def list_slots(self, start_iso: str, end_iso: str, limit: int = 200) -> List[Dict[str, Any]]:
        resp = (
            self.client.table("slots")
            .select("id,start_at,end_at,is_enabled")
            .eq("is_enabled", True)
            .gte("start_at", start_iso)
            .lt("start_at", end_iso)
            .order("start_at", desc=False)
            .limit(limit)
            .execute()
        )
        data, err = _unwrap(resp)
        if err:
            raise DBError(str(err))
        return data or []

    def booked_slot_ids(self, start_iso: str, end_iso: str) -> List[str]:
        resp = (
            self.client.table("appointments")
            .select("slot_id")
            .eq("status", "booked")
            .gte("start_at", start_iso)
            .lt("start_at", end_iso)
            .execute()
        )
        data, err = _unwrap(resp)
        if err:
            raise DBError(str(err))
        return [str(r["slot_id"]) for r in (data or [])]

    # -------------------------
    # Appointments
    # -------------------------
    def book_appointment(
        self,
        contact_number: str,
        slot_id: str,
        title: Optional[str],
        notes: Optional[str],
        source_session_id: Optional[str],
    ) -> Dict[str, Any]:
        contact_number = normalize_phone(contact_number)
        payload: Dict[str, Any] = {
            "contact_number": contact_number,
            "slot_id": slot_id,
            "source_session_id": source_session_id,
        }
        if title:
            payload["title"] = title
        if notes:
            payload["notes"] = notes

        resp = (
            self.client.table("appointments")
            .insert(payload, returning="representation")
            .execute()
        )
        data, err = _unwrap(resp)
        if err:
            # common case: unique index violation (double booking)
            raise DBError(str(err))
        return data[0]

    def list_appointments(self, contact_number: str, include_cancelled: bool, limit: int = 10) -> List[Dict[str, Any]]:
        contact_number = normalize_phone(contact_number)
        q = (
            self.client.table("appointments")
            .select("id,slot_id,title,notes,start_at,end_at,status,created_at,cancelled_at")
            .eq("contact_number", contact_number)
            .order("start_at", desc=True)
            .limit(limit)
        )
        if not include_cancelled:
            q = q.eq("status", "booked")

        resp = q.execute()
        data, err = _unwrap(resp)
        if err:
            raise DBError(str(err))
        return data or []

    def cancel_appointment(self, appointment_id: str) -> Dict[str, Any]:
        resp = (
            self.client.table("appointments")
            .update({"status": "cancelled", "cancelled_at": "now()"}, returning="representation")
            .eq("id", appointment_id)
            .execute()
        )
        data, err = _unwrap(resp)
        if err:
            raise DBError(str(err))
        if not data:
            raise DBError("Appointment not found")
        return data[0]

    def modify_appointment(self, appointment_id: str, new_slot_id: str) -> Dict[str, Any]:
        resp = (
            self.client.table("appointments")
            .update({"slot_id": new_slot_id}, returning="representation")
            .eq("id", appointment_id)
            .execute()
        )
        data, err = _unwrap(resp)
        if err:
            raise DBError(str(err))
        if not data:
            raise DBError("Appointment not found")
        return data[0]

    # -------------------------
    # Logging
    # -------------------------
    def insert_tool_event(
        self,
        session_id: str,
        tool: str,
        input_json: Dict[str, Any],
        output_json: Dict[str, Any],
        ok: bool,
        error_message: Optional[str],
    ) -> None:
        payload = {
            "session_id": session_id,
            "tool": tool,
            "input": input_json,
            "output": output_json,
            "ok": ok,
            "error_message": error_message,
        }
        resp = self.client.table("tool_events").insert(payload).execute()
        _, err = _unwrap(resp)
        if err:
            raise DBError(str(err))
        
    # -------------------------
    # Call Messages / Summaries
    # -------------------------
    def insert_call_message(
        self,
        session_id: str,
        role: str,
        content: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "session_id": session_id,
            "role": role,
            "content": content,
            "meta": meta or {},
        }
        resp = self.client.table("call_messages").insert(payload, returning="representation").execute()
        data, err = _unwrap(resp)
        if err:
            raise DBError(str(err))
        return data[0]

    def list_call_messages(self, session_id: str, limit: int = 80) -> List[Dict[str, Any]]:
        resp = (
            self.client.table("call_messages")
            .select("role,content,meta,created_at")
            .eq("session_id", session_id)
            .order("created_at", desc=False)
            .limit(max(1, min(limit, 200)))
            .execute()
        )
        data, err = _unwrap(resp)
        if err:
            raise DBError(str(err))
        return data or []

    def list_appointments_by_session(self, session_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        resp = (
            self.client.table("appointments")
            .select("id,slot_id,title,notes,start_at,end_at,status,created_at,cancelled_at,source_session_id,contact_number")
            .eq("source_session_id", session_id)
            .order("start_at", desc=False)
            .limit(max(1, min(limit, 100)))
            .execute()
        )
        data, err = _unwrap(resp)
        if err:
            raise DBError(str(err))
        return data or []

    def upsert_call_summary(
        self,
        session_id: str,
        summary_text: str,
        booked_appointments: Any,
        preferences: Any,
        model: Optional[str] = None,
        generation_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "session_id": session_id,
            "summary_text": summary_text,
            "booked_appointments": booked_appointments,
            "preferences": preferences,
        }
        if model:
            payload["model"] = model
        if generation_ms is not None:
            payload["generation_ms"] = generation_ms

        resp = (
            self.client.table("call_summaries")
            .upsert(payload, on_conflict="session_id", returning="representation")
            .execute()
        )
        data, err = _unwrap(resp)
        if err:
            raise DBError(str(err))
        return data[0]

