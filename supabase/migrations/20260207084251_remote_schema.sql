


SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;


CREATE EXTENSION IF NOT EXISTS "pg_cron" WITH SCHEMA "pg_catalog";






COMMENT ON SCHEMA "public" IS 'standard public schema';



CREATE EXTENSION IF NOT EXISTS "pg_graphql" WITH SCHEMA "graphql";






CREATE EXTENSION IF NOT EXISTS "pg_stat_statements" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "pgcrypto" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "supabase_vault" WITH SCHEMA "vault";






CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA "extensions";






CREATE TYPE "public"."appointment_status" AS ENUM (
    'booked',
    'cancelled'
);


ALTER TYPE "public"."appointment_status" OWNER TO "postgres";


CREATE TYPE "public"."call_session_status" AS ENUM (
    'active',
    'ended'
);


ALTER TYPE "public"."call_session_status" OWNER TO "postgres";


CREATE TYPE "public"."tool_name" AS ENUM (
    'identify_user',
    'fetch_slots',
    'book_appointment',
    'retrieve_appointments',
    'cancel_appointment',
    'modify_appointment',
    'end_conversation'
);


ALTER TYPE "public"."tool_name" OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."fill_appointment_times_from_slot"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
declare
  v_start timestamptz;
  v_end timestamptz;
  v_enabled boolean;
begin
  select start_at, end_at, is_enabled
    into v_start, v_end, v_enabled
  from public.slots
  where id = new.slot_id;

  if not found then
    raise exception 'Invalid slot_id: %', new.slot_id;
  end if;

  if v_enabled is not true then
    raise exception 'Slot is disabled and cannot be booked: %', new.slot_id;
  end if;

  new.start_at := v_start;
  new.end_at := v_end;

  return new;
end;
$$;


ALTER FUNCTION "public"."fill_appointment_times_from_slot"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."generate_slots"("p_start_date" "date" DEFAULT (("now"() AT TIME ZONE 'Asia/Kolkata'::"text"))::"date", "p_days" integer DEFAULT 14, "p_open" time without time zone DEFAULT '10:00:00'::time without time zone, "p_close" time without time zone DEFAULT '17:30:00'::time without time zone, "p_slot_mins" integer DEFAULT 30) RETURNS integer
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$
declare
  inserted int;
begin
  insert into public.slots (start_at, end_at, is_enabled)
  select
    ts as start_at,
    ts + make_interval(mins => p_slot_mins) as end_at,
    true
  from (
    select
      gs_day::date as d,
      (gs_day::date + p_open) at time zone 'Asia/Kolkata' as open_ts,
      (gs_day::date + p_close) at time zone 'Asia/Kolkata' as close_ts
    from generate_series(p_start_date, p_start_date + (p_days - 1), interval '1 day') as gs_day
  ) b
  cross join lateral generate_series(
    b.open_ts,
    b.close_ts - make_interval(mins => p_slot_mins),
    make_interval(mins => p_slot_mins)
  ) as ts
  on conflict (start_at) do nothing;

  get diagnostics inserted = row_count;
  return inserted;
end;
$$;


ALTER FUNCTION "public"."generate_slots"("p_start_date" "date", "p_days" integer, "p_open" time without time zone, "p_close" time without time zone, "p_slot_mins" integer) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."set_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
begin
  new.updated_at = now();
  return new;
end;
$$;


ALTER FUNCTION "public"."set_updated_at"() OWNER TO "postgres";

SET default_tablespace = '';

SET default_table_access_method = "heap";


CREATE TABLE IF NOT EXISTS "public"."appointments" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "contact_number" "text" NOT NULL,
    "slot_id" "uuid" NOT NULL,
    "title" "text",
    "notes" "text",
    "start_at" timestamp with time zone NOT NULL,
    "end_at" timestamp with time zone NOT NULL,
    "status" "public"."appointment_status" DEFAULT 'booked'::"public"."appointment_status" NOT NULL,
    "source_session_id" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "cancelled_at" timestamp with time zone
);


ALTER TABLE "public"."appointments" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."call_messages" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "session_id" "uuid" NOT NULL,
    "role" "text" NOT NULL,
    "content" "text" NOT NULL,
    "meta" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "call_messages_role_check" CHECK (("role" = ANY (ARRAY['user'::"text", 'assistant'::"text", 'system'::"text"])))
);


ALTER TABLE "public"."call_messages" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."call_sessions" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "room_name" "text" NOT NULL,
    "contact_number" "text",
    "status" "public"."call_session_status" DEFAULT 'active'::"public"."call_session_status" NOT NULL,
    "started_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "ended_at" timestamp with time zone,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL
);


ALTER TABLE "public"."call_sessions" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."call_summaries" (
    "session_id" "uuid" NOT NULL,
    "summary_text" "text" DEFAULT ''::"text" NOT NULL,
    "booked_appointments" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "preferences" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "model" "text",
    "generation_ms" integer,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."call_summaries" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."contacts" (
    "contact_number" "text" NOT NULL,
    "name" "text",
    "metadata" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "last_seen_at" timestamp with time zone
);


ALTER TABLE "public"."contacts" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."slots" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "start_at" timestamp with time zone NOT NULL,
    "end_at" timestamp with time zone NOT NULL,
    "is_enabled" boolean DEFAULT true NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "chk_slot_end_after_start" CHECK (("end_at" > "start_at"))
);


ALTER TABLE "public"."slots" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."tool_events" (
    "id" bigint NOT NULL,
    "session_id" "uuid" NOT NULL,
    "tool" "public"."tool_name" NOT NULL,
    "input" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "output" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "ok" boolean DEFAULT true NOT NULL,
    "error_message" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."tool_events" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."tool_events_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE "public"."tool_events_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."tool_events_id_seq" OWNED BY "public"."tool_events"."id";



ALTER TABLE ONLY "public"."tool_events" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."tool_events_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."appointments"
    ADD CONSTRAINT "appointments_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."call_messages"
    ADD CONSTRAINT "call_messages_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."call_sessions"
    ADD CONSTRAINT "call_sessions_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."call_summaries"
    ADD CONSTRAINT "call_summaries_pkey" PRIMARY KEY ("session_id");



ALTER TABLE ONLY "public"."call_summaries"
    ADD CONSTRAINT "call_summaries_session_id_key" UNIQUE ("session_id");



ALTER TABLE ONLY "public"."contacts"
    ADD CONSTRAINT "contacts_pkey" PRIMARY KEY ("contact_number");



ALTER TABLE ONLY "public"."slots"
    ADD CONSTRAINT "slots_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tool_events"
    ADD CONSTRAINT "tool_events_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."slots"
    ADD CONSTRAINT "uq_slots_start_at" UNIQUE ("start_at");



CREATE INDEX "call_messages_session_id_idx" ON "public"."call_messages" USING "btree" ("session_id", "created_at");



CREATE INDEX "idx_appointments_contact_time" ON "public"."appointments" USING "btree" ("contact_number", "start_at");



CREATE INDEX "idx_call_sessions_contact_number" ON "public"."call_sessions" USING "btree" ("contact_number");



CREATE INDEX "idx_call_sessions_room_name" ON "public"."call_sessions" USING "btree" ("room_name");



CREATE INDEX "idx_slots_enabled_time" ON "public"."slots" USING "btree" ("is_enabled", "start_at");



CREATE INDEX "idx_tool_events_session_time" ON "public"."tool_events" USING "btree" ("session_id", "created_at");



CREATE UNIQUE INDEX "uq_appointments_slot_booked" ON "public"."appointments" USING "btree" ("slot_id") WHERE ("status" = 'booked'::"public"."appointment_status");



CREATE OR REPLACE TRIGGER "trg_appointments_updated_at" BEFORE UPDATE ON "public"."appointments" FOR EACH ROW EXECUTE FUNCTION "public"."set_updated_at"();



CREATE OR REPLACE TRIGGER "trg_appt_fill_times" BEFORE INSERT OR UPDATE OF "slot_id" ON "public"."appointments" FOR EACH ROW EXECUTE FUNCTION "public"."fill_appointment_times_from_slot"();



CREATE OR REPLACE TRIGGER "trg_call_summaries_updated_at" BEFORE UPDATE ON "public"."call_summaries" FOR EACH ROW EXECUTE FUNCTION "public"."set_updated_at"();



CREATE OR REPLACE TRIGGER "trg_contacts_updated_at" BEFORE UPDATE ON "public"."contacts" FOR EACH ROW EXECUTE FUNCTION "public"."set_updated_at"();



CREATE OR REPLACE TRIGGER "trg_slots_updated_at" BEFORE UPDATE ON "public"."slots" FOR EACH ROW EXECUTE FUNCTION "public"."set_updated_at"();



ALTER TABLE ONLY "public"."appointments"
    ADD CONSTRAINT "appointments_contact_number_fkey" FOREIGN KEY ("contact_number") REFERENCES "public"."contacts"("contact_number") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."appointments"
    ADD CONSTRAINT "appointments_slot_id_fkey" FOREIGN KEY ("slot_id") REFERENCES "public"."slots"("id") ON DELETE RESTRICT;



ALTER TABLE ONLY "public"."appointments"
    ADD CONSTRAINT "appointments_source_session_id_fkey" FOREIGN KEY ("source_session_id") REFERENCES "public"."call_sessions"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."call_messages"
    ADD CONSTRAINT "call_messages_session_id_fkey" FOREIGN KEY ("session_id") REFERENCES "public"."call_sessions"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."call_sessions"
    ADD CONSTRAINT "call_sessions_contact_number_fkey" FOREIGN KEY ("contact_number") REFERENCES "public"."contacts"("contact_number") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."call_summaries"
    ADD CONSTRAINT "call_summaries_session_id_fkey" FOREIGN KEY ("session_id") REFERENCES "public"."call_sessions"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."tool_events"
    ADD CONSTRAINT "tool_events_session_id_fkey" FOREIGN KEY ("session_id") REFERENCES "public"."call_sessions"("id") ON DELETE CASCADE;



ALTER TABLE "public"."appointments" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."call_messages" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."call_sessions" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."call_summaries" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."contacts" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."slots" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."tool_events" ENABLE ROW LEVEL SECURITY;




ALTER PUBLICATION "supabase_realtime" OWNER TO "postgres";





GRANT USAGE ON SCHEMA "public" TO "postgres";
GRANT USAGE ON SCHEMA "public" TO "anon";
GRANT USAGE ON SCHEMA "public" TO "authenticated";
GRANT USAGE ON SCHEMA "public" TO "service_role";














































































































































































GRANT ALL ON FUNCTION "public"."fill_appointment_times_from_slot"() TO "anon";
GRANT ALL ON FUNCTION "public"."fill_appointment_times_from_slot"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."fill_appointment_times_from_slot"() TO "service_role";



GRANT ALL ON FUNCTION "public"."generate_slots"("p_start_date" "date", "p_days" integer, "p_open" time without time zone, "p_close" time without time zone, "p_slot_mins" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."generate_slots"("p_start_date" "date", "p_days" integer, "p_open" time without time zone, "p_close" time without time zone, "p_slot_mins" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."generate_slots"("p_start_date" "date", "p_days" integer, "p_open" time without time zone, "p_close" time without time zone, "p_slot_mins" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."set_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."set_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."set_updated_at"() TO "service_role";
























GRANT ALL ON TABLE "public"."appointments" TO "anon";
GRANT ALL ON TABLE "public"."appointments" TO "authenticated";
GRANT ALL ON TABLE "public"."appointments" TO "service_role";



GRANT ALL ON TABLE "public"."call_messages" TO "anon";
GRANT ALL ON TABLE "public"."call_messages" TO "authenticated";
GRANT ALL ON TABLE "public"."call_messages" TO "service_role";



GRANT ALL ON TABLE "public"."call_sessions" TO "anon";
GRANT ALL ON TABLE "public"."call_sessions" TO "authenticated";
GRANT ALL ON TABLE "public"."call_sessions" TO "service_role";



GRANT ALL ON TABLE "public"."call_summaries" TO "anon";
GRANT ALL ON TABLE "public"."call_summaries" TO "authenticated";
GRANT ALL ON TABLE "public"."call_summaries" TO "service_role";



GRANT ALL ON TABLE "public"."contacts" TO "anon";
GRANT ALL ON TABLE "public"."contacts" TO "authenticated";
GRANT ALL ON TABLE "public"."contacts" TO "service_role";



GRANT ALL ON TABLE "public"."slots" TO "anon";
GRANT ALL ON TABLE "public"."slots" TO "authenticated";
GRANT ALL ON TABLE "public"."slots" TO "service_role";



GRANT ALL ON TABLE "public"."tool_events" TO "anon";
GRANT ALL ON TABLE "public"."tool_events" TO "authenticated";
GRANT ALL ON TABLE "public"."tool_events" TO "service_role";



GRANT ALL ON SEQUENCE "public"."tool_events_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."tool_events_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."tool_events_id_seq" TO "service_role";









ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "service_role";































