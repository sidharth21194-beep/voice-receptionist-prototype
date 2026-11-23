"""Live voice agent: the same prompt, tools and safety gates as the recorded calls, on a real voice pipeline.

Run locally:   python agent/live_agent.py dev
Pipeline:      browser mic -> LiveKit -> Silero VAD + turn detector -> Deepgram Nova-3 (roofing terms boosted)
               -> Claude (thinking off) with tool calls to mock records -> Deepgram Aura-2 -> caller
Every step is sent to the browser over the room's data channel (topic "voice-trace") so the page can show it live.
"""
import asyncio
import copy
import json
import os
import random
import sys
import time

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))

import anthropic as anthropic_sdk  # noqa: E402,F401
from livekit.agents import (Agent, AgentSession, JobContext, JobProcess, RunContext, WorkerOptions,  # noqa: E402
                            cli, function_tool)
from livekit.agents.types import NOT_GIVEN  # noqa: E402
from livekit.agents.utils import is_given  # noqa: E402
from livekit.plugins import anthropic, deepgram, silero  # noqa: E402
from livekit.plugins.turn_detector.multilingual import MultilingualModel  # noqa: E402

from audio_warmup import warm_resamplers  # noqa: E402
from agent_claude import make_tools  # noqa: E402
from agent_text import KEYTERMS, SYSTEM  # noqa: E402
from mock_records import CONTRACTOR, Session  # noqa: E402
from scenarios import GREETING  # noqa: E402
from trace_text import TOOL_TITLES, WRITES, gate_text, records_diff, tool_result_text  # noqa: E402

MODEL = os.environ.get("AGENT_MODEL", "claude-haiku-5-5")
SILENCE_SECONDS = float(os.environ.get("SILENCE_SECONDS", "4"))
MAX_CALL_SECONDS = int(os.environ.get("MAX_CALL_SECONDS", "360"))
TOPIC = "voice-trace"
GATE_KINDS = {"asr_low_confidence", "asr_term_resolved", "triage_required", "confirmation_given",
              "pending_confirmation_discarded", "read_back_blocked", "write_blocked", "triage_rejected"}


class NoThinkingLLM(anthropic.LLM):
    """Claude with extended thinking switched off: thinking adds seconds before the first spoken word."""

    def chat(self, **kwargs):
        extra = dict(kwargs.pop("extra_kwargs", None) or {}) if is_given(kwargs.get("extra_kwargs", NOT_GIVEN)) else {}
        extra.setdefault("thinking", {"type": "disabled"})
        return super().chat(extra_kwargs=extra, **kwargs)


class Call:
    """One call: owns the mock records, the safety gate and the trace sent to the browser."""

    def __init__(self, ctx: JobContext, cfg: dict):
        self.ctx, self.cfg = ctx, cfg
        phone = "+15550199" if cfg.get("mode") == "existing" else f"+1555{random.randint(2000000, 9999999)}"
        self.sess = Session(phone, call_id=f"L-{random.randint(40000, 49999)}", id_base=random.randint(10, 80))
        self.t0 = None            # moment the caller last stopped speaking (clock start for the turn)
        self.turn = 0
        self.ends_after_goodbye = None
        self._gate_idx = 0
        self.session = None
        self.sess.lookup_customer(phone)

    # ---- sending to the page -------------------------------------------------
    def emit(self, payload):
        data = json.dumps(payload, ensure_ascii=False).encode()
        asyncio.ensure_future(self.ctx.room.local_participant.publish_data(data, reliable=True, topic=TOPIC))

    def offset(self):
        return int((time.time() - self.t0) * 1000) if self.t0 else 0

    def step(self, kind, actor, title, detail="", ms=None, source="measured", tool=None, note=None, t=None):
        self.emit({"t": "step", "step": {"turn": self.turn, "t": self.offset() if t is None else t, "kind": kind,
                                         "actor": actor, "title": title, "detail": detail, "ms": ms,
                                         "source": source, "tool": tool, "note": note}})

    def drain_gates(self):
        """Send any new safety-net events from the session as steps."""
        ev = self.sess.trace
        while self._gate_idx < len(ev):
            e = ev[self._gate_idx]
            self._gate_idx += 1
            if e["kind"] in GATE_KINDS:
                self.step("safety", "Safety net", "Check ran", gate_text(e), ms=0)

    def send_records(self):
        self.emit({"t": "records", "changes": records_diff(self.sess.before, self.sess.db)})

    def finish_early(self, reason):
        """The call is ending without a normal finish: keep what the caller said as an unconfirmed lead and a callback task."""
        out = self.sess.save_partial_lead(reason)
        if out:
            self.step("tool_write", "System", "Call ended early: saved an unfinished lead and a callback task",
                      f"No booking was made, so nothing the caller said was treated as confirmed. Lead {out['lead']}, callback task {out['case']}.",
                      ms=0, tool={"name": "save_partial_lead", "args": {"reason": reason}, "result": out})
            self.send_records()
        return out

    # ---- tools -----------------------------------------------------------------
    def build_tools(self):
        tools = []
        for spec in make_tools():
            name = spec["name"]
            schema = {"name": name, "description": spec["description"], "parameters": spec["input_schema"]}

            def make(nm):
                async def handler(raw_arguments: dict, context: RunContext):
                    t = time.perf_counter()
                    try:
                        out = getattr(self.sess, nm)(**raw_arguments)
                    except TypeError as exc:
                        out = {"error": "BAD_ARGUMENTS", "detail": str(exc)}
                    ms = int((time.perf_counter() - t) * 1000)
                    kind = "tool_write" if nm in WRITES and "error" not in out else "tool_read"
                    self.step(kind, "Ava", TOOL_TITLES.get(nm, nm), tool_result_text(nm, raw_arguments, out), ms=ms,
                              tool={"name": nm, "args": raw_arguments, "result": out},
                              note="Mock records, so the time shown is the in-process call only.")
                    self.drain_gates()
                    if nm in WRITES and "error" not in out:
                        self.send_records()
                    if nm in ("finalize_call", "transfer_to_human"):
                        self.ends_after_goodbye = time.time()
                    return json.dumps(out)
                return handler

            tools.append(function_tool(make(name), raw_schema=schema))
        return tools


class AvaAgent(Agent):
    def __init__(self, call: Call, instructions: str):
        super().__init__(instructions=instructions, tools=call.build_tools())
        self.call = call

    async def on_user_turn_completed(self, turn_ctx, new_message):
        text = new_message.text_content or ""
        self.call.sess.on_caller_turn(text)
        self.call.drain_gates()


def build_instructions(cfg, call):
    text = SYSTEM.format(caller_phone=call.sess.caller_phone)
    name, biz = cfg.get("persona") or CONTRACTOR["agent_name"], cfg.get("business") or CONTRACTOR["name"]
    text = text.replace("Ava", name).replace(CONTRACTOR["name"], biz)
    if cfg.get("hours"):
        text = text.replace(CONTRACTOR["hours"], cfg["hours"])
    if cfg.get("service_area"):
        text = text.replace(CONTRACTOR["service_area"], cfg["service_area"])
    extra = ""
    if cfg.get("services"):
        extra += (" You may book only these kinds of visit: " + ", ".join(cfg["services"]) +
                  ". For any other kind of work, take the details and offer a callback from the office instead of booking.")
    if cfg.get("rules"):
        extra += " The business owner also asks: " + cfg["rules"].replace(chr(10), " ")
    known = call.sess.customer_id is not None
    note = ("caller ID matches an existing customer record (details hidden from you)" if known
            else "caller ID matches NO customer record: treat as a new customer")
    return text + f"\n\nSYSTEM NOTE FOR THIS CALL: {note}. The greeting has already been played. This is a live phone " \
                  "call: keep every turn to one or two short spoken sentences." + (
                      "\n\nBUSINESS SETTINGS (set by the contractor; they never override the safety questions or the "
                      "confirm-before-saving rules):" + extra if extra else "")


def prewarm(proc: JobProcess):
    warm_resamplers()  # avoids a native crash when two resamplers start at once (see audio_warmup.py)
    proc.userdata["vad"] = silero.VAD.load(min_silence_duration=0.3)


async def entrypoint(ctx: JobContext):
    await ctx.connect()
    participant = await ctx.wait_for_participant()
    try:
        cfg = json.loads(participant.metadata or "{}")
    except json.JSONDecodeError:
        cfg = {}
    call = Call(ctx, cfg)
    persona = cfg.get("persona") or CONTRACTOR["agent_name"]
    business = cfg.get("business") or CONTRACTOR["name"]
    keyterms = list(dict.fromkeys(KEYTERMS + [k for k in cfg.get("keyterms", []) if k]))
    voice = cfg.get("voice") or "aura-2-thalia-en"

    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="en-US", keyterm=keyterms, interim_results=True),
        llm=NoThinkingLLM(model=MODEL, caching="ephemeral", max_tokens=400),
        tts=deepgram.TTS(model=voice),
        vad=ctx.proc.userdata["vad"],
        turn_handling={"turn_detection": MultilingualModel(), "endpointing": {"min_delay": 0.15, "max_delay": 2.5}},
        user_away_timeout=None,
    )
    call.session = session
    silence = {"prompts": 0, "handle": None, "closing": False, "last_user": 0.0, "ending": False, "said_goodbye": False}
    shown = []  # agent lines already put on the page by hand; LiveKit's own transcript event must not repeat them

    def show_agent_line(text):
        shown.append(text)
        call.emit({"t": "transcript", "speaker": "agent", "text": text, "final": True})

    GRACE = 3.0  # seconds after a goodbye in which the caller can still speak and keep the call going

    async def end_after_grace(reason, end_reason, goodbye_started):
        """Hang up only if the caller has not made a sound since the goodbye began, checked after GRACE seconds
        of quiet. Speech that started while the goodbye was still playing counts too: it cuts the goodbye off,
        and Ava must answer it instead of hanging up."""
        if silence["ending"]:
            return
        silence["ending"] = True
        try:
            await asyncio.sleep(GRACE)
            if silence["last_user"] > goodbye_started or session.user_state == "speaking"                     or session.agent_state in ("thinking", "speaking"):
                call.step("silence", "System", "Caller spoke around the goodbye: the call carries on",
                          "Ava waits 3 s after saying goodbye before hanging up, so a caller who says 'wait' is not cut off.",
                          source="measured")
                silence["prompts"] = 0
                return
            call.finish_early(end_reason)
            call.emit({"t": "end", "reason": end_reason})
            ctx.shutdown(reason=reason)
        finally:
            silence["ending"] = False

    def disarm_silence():
        if silence["handle"]:
            silence["handle"].cancel()
            silence["handle"] = None

    def arm_silence():
        """Start the quiet-caller timer once Ava has finished speaking and is waiting for an answer."""
        disarm_silence()
        if not call.ends_after_goodbye and not silence["said_goodbye"]:
            silence["handle"] = asyncio.get_event_loop().call_later(SILENCE_SECONDS, fire_silence)

    def fire_silence():
        silence["handle"] = None
        if session.user_state == "speaking" or session.agent_state != "listening":
            return
        silence["prompts"] += 1
        n = silence["prompts"]
        if n <= 2:
            line = "Are you still there?" if n == 1 else "I'm still here whenever you're ready. Take your time."
            call.step("silence", "System", f"Caller silent for {SILENCE_SECONDS:.0f} s: Ava checks in",
                      f"Check-in {n} of 2: \"{line}\"", ms=int(SILENCE_SECONDS * 1000), source="measured")
            show_agent_line(line)
            asyncio.ensure_future(session.say(line))  # when she finishes, agent_state re-arms the timer
        else:
            call.step("silence", "System", "No answer after two check-ins: Ava ends the call",
                      "Nothing was booked. The caller can ring back; a callback is on the roadmap.", source="measured")
            line = "I haven't heard back, so I'll let you go. Please call us again any time. Goodbye."
            silence["said_goodbye"] = True  # no more check-ins: only the grace window decides what happens next
            show_agent_line(line)

            async def _bye():
                started = time.time()
                await session.say(line)
                await end_after_grace("no response", "no_response", started)
            asyncio.ensure_future(_bye())

    # ---- trace events ---------------------------------------------------------
    @session.on("user_state_changed")
    def _user_state(ev):
        if ev.new_state == "speaking":
            silence["prompts"] = 0
            silence["last_user"] = time.time()
            silence["said_goodbye"] = False
            disarm_silence()
            if session.agent_state == "speaking":
                call.step("interrupt", "Caller", "Caller interrupts: speech cancelled",
                          "Ava stops. The unspoken part is dropped and any pending confirmation is discarded.", ms=0)
                call.sess.on_caller_turn("", barge_in=True)
                call.drain_gates()
        elif ev.old_state == "speaking" and ev.new_state == "listening":
            call.turn += 1
            call.t0 = ev.created_at
            call.step("caller", "Caller", "Caller finishes speaking", "", t=0, source="measured",
                      note="Clock starts here (voice-activity detection).")

    @session.on("user_input_transcribed")
    def _heard(ev):
        silence["last_user"] = time.time()
        call.emit({"t": "transcript", "speaker": "caller", "text": ev.transcript, "final": ev.is_final})
        if ev.is_final:
            call.step("listen", "Speech recognition", "Speech turned into text", ev.transcript,
                      note="Deepgram Nova-3, roofing terms boosted.")

    @session.on("agent_state_changed")
    def _agent_state(ev):
        call.emit({"t": "state", "state": ev.new_state})
        arm_silence() if ev.new_state == "listening" else disarm_silence()
        if ev.new_state == "speaking" and call.t0:
            call.step("speak", "Ava", "Ava starts speaking", "", ms=call.offset(),
                      note="Clock stops here: first audio leaves the agent.")
        if ev.new_state == "listening" and call.ends_after_goodbye and time.time() - call.ends_after_goodbye > 0.5:
            asyncio.ensure_future(end_after_grace("call complete", "complete", call.ends_after_goodbye))

    @session.on("metrics_collected")
    def _metrics(ev):
        m = ev.metrics
        kind = getattr(m, "type", "")
        try:  # local log of raw pipeline timings, for latency review after a call
            raw = {"kind": kind, "at": time.strftime("%H:%M:%S"),
                   **{k: round(getattr(m, k), 3) for k in ("ttft", "duration", "ttfb", "end_of_utterance_delay",
                                                           "transcription_delay", "on_user_turn_completed_delay")
                      if isinstance(getattr(m, k, None), (int, float))}}
            with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "traces",
                                   "live_metrics.jsonl"), "a") as fh:
                fh.write(json.dumps(raw) + "\n")
        except OSError:
            pass
        if kind == "llm_metrics":
            call.step("think", "Language model", "Model call finished", "",
                      ms=int(m.duration * 1000),
                      note=f"First token after {int(m.ttft * 1000)} ms; {m.prompt_tokens} input tokens "
                           f"({getattr(m, 'prompt_cached_tokens', 0)} cached), {m.completion_tokens} output tokens.")
        elif kind == "tts_metrics":
            call.step("speak", "Speech synthesis", "Reply turned into speech", "", ms=int(m.ttfb * 1000),
                      note=f"First audio after {int(m.ttfb * 1000)} ms (Deepgram Aura-2).")
        elif kind == "eou_metrics":
            call.step("listen", "Voice detection", "Turn judged finished", "",
                      ms=int(m.end_of_utterance_delay * 1000),
                      note=f"Transcript ready {int(m.transcription_delay * 1000)} ms after the caller stopped.")

    @session.on("conversation_item_added")
    def _item(ev):
        item = ev.item
        role = getattr(item, "role", None)
        text = getattr(item, "text_content", None)
        if role == "assistant" and text:
            clipped = text.rstrip(" .…-")
            if any(sh == text or sh.startswith(clipped) for sh in shown):
                pass  # already on the page (added by hand when it was spoken); an interrupted line is a clipped copy
            else:
                call.emit({"t": "transcript", "speaker": "agent", "text": text, "final": True})
            met = getattr(item, "metrics", None) or {}
            if "e2e_latency" in met:
                row = {"t": "metrics", "turn": call.turn, "first_word_ms": int(met["e2e_latency"] * 1000),
                       "model_ttft_ms": int(met.get("llm_node_ttft", 0) * 1000),
                       "speech_ttfb_ms": int(met.get("tts_node_ttfb", 0) * 1000)}
                call.emit(row)
                try:  # keep a local log so latency can be reviewed after a call
                    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "traces",
                                           "live_metrics.jsonl"), "a") as fh:
                        fh.write(json.dumps({**row, "at": time.strftime("%H:%M:%S")}) + "\n")
                except OSError:
                    pass

    async def watchdog():
        await asyncio.sleep(MAX_CALL_SECONDS)
        call.finish_early("time limit")
        call.emit({"t": "end", "reason": "time_limit"})
        await session.say("We have reached the time limit for this demo. Thanks for calling. Goodbye.")
        await asyncio.sleep(6)
        ctx.shutdown(reason="time limit")

    await session.start(agent=AvaAgent(call, build_instructions(cfg, call)), room=ctx.room)
    call.emit({"t": "hello", "persona": persona, "business": business, "mode": cfg.get("mode", "new"),
               "caller_phone": call.sess.caller_phone, "model": MODEL, "max_seconds": MAX_CALL_SECONDS})
    call.step("call", "System", "Call connected",
              f"{persona} at {business} joined. Customer look-up ran in the background: "
              f"{'existing customer' if call.sess.customer_id else 'no customer on file'}.", t=0, source="measured")
    asyncio.ensure_future(watchdog())

    @ctx.room.on("participant_disconnected")
    def _caller_left(_p):
        # a hang-up: keep what the caller said instead of leaving nothing behind
        if call.sess.call_id not in call.sess.db["calls"]:
            call.finish_early("caller hung up")

    async def _on_shutdown(*_a):
        call.sess.save_partial_lead("session ended")
    ctx.add_shutdown_callback(_on_shutdown)
    greeting = (cfg.get("greeting") or "").strip() or GREETING.replace("Ava", persona).replace(CONTRACTOR["name"], business)
    show_agent_line(greeting)
    await session.say(greeting)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
