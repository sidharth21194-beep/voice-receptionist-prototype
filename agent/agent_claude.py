"""Claude variant of the text-mode agent. Same prompt, same mock tools, same gate as agent_text.py (Gemini).

Usage: python agent/agent_claude.py <scenario> [model]
The model is a single setting: swapping providers changes only this file's client call.
Records time to first token (ttft_ms) and total time per model call. Text mode, so this is model time only.
"""
import inspect
import json
import os
import re
import sys
import time

from anthropic import Anthropic
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from agent_text import SYSTEM  # noqa: E402  (shared prompt)
from mock_records import TOOL_SPECS, Session  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

DEFAULT_MODEL = os.environ.get("AGENT_MODEL", "claude-haiku-5-5")


def make_tools():
    tools = []
    for spec in TOOL_SPECS:
        if spec["name"] == "lookup_customer":  # run by the orchestrator while the greeting plays
            continue
        props = {k: {"type": t, "description": d} for k, (t, d) in spec["params"].items()}
        sig = inspect.signature(getattr(Session, spec["name"]))
        required = [k for k in props if sig.parameters[k].default is inspect.Parameter.empty]
        tools.append({"name": spec["name"], "description": spec["description"],
                      "input_schema": {"type": "object", "properties": props, "required": required}})
    return tools


def run(scenario_name, model=DEFAULT_MODEL):
    sc = SCENARIOS[scenario_name]
    session = Session(sc["caller_phone"], call_id=sc.get("call_id", "L-31007"), id_base=sc.get("id_base", 0))
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    system = [{"type": "text", "text": SYSTEM.format(caller_phone=sc["caller_phone"]),
               "cache_control": {"type": "ephemeral"}}]
    tools = make_tools()
    messages, turns = [], []
    agent_last = ""

    def call_model():
        t0 = time.perf_counter()
        ttft = None
        with client.messages.stream(model=model, max_tokens=400, thinking={"type": "disabled"}, system=system,
                                    tools=tools, messages=messages) as stream:
            for event in stream:
                if ttft is None and event.type in ("content_block_start", "text"):
                    ttft = int((time.perf_counter() - t0) * 1000)
            msg = stream.get_final_message()
        return msg, ttft or 0, int((time.perf_counter() - t0) * 1000)

    concat_pre_tool = scenario_name == "emergency_sim"  # the exact safety line is often said just before the tool call

    def agent_turn(user_text):
        nonlocal agent_last
        messages.append({"role": "user", "content": user_text})
        said_before_tools = ""  # text the model spoke in the same message as a tool call (live, this is spoken too)
        for _ in range(8):
            msg, ttft_ms, llm_ms = call_model()
            blocks = [b.model_dump(exclude_none=True) for b in msg.content]
            messages.append({"role": "assistant", "content": blocks})
            uses = [b for b in msg.content if b.type == "tool_use"]
            if uses:
                said_before_tools = (said_before_tools + " " + "".join(
                    b.text for b in msg.content if b.type == "text")).strip()
            if not uses:
                text = "".join(b.text for b in msg.content if b.type == "text").strip()
                if concat_pre_tool and said_before_tools and said_before_tools not in text:  # text spoken alongside a tool call is heard too
                    text = (said_before_tools + " " + text).strip()
                if not text:  # the model finished a tool step silently: ask it to say its line out loud
                    messages.pop()
                    messages.append({"role": "user", "content": "[system: say your reply to the caller out loud now]"})
                    continue
                session.log("agent_says", text=text, llm_ms=llm_ms, ttft_ms=ttft_ms,
                            usage={"in": msg.usage.input_tokens, "out": msg.usage.output_tokens,
                                   "cache_read": getattr(msg.usage, "cache_read_input_tokens", 0)})
                agent_last = text
                return text
            results = []
            for u in uses:
                t1 = time.perf_counter()
                try:
                    out = getattr(session, u.name)(**u.input)
                except TypeError as exc:  # malformed tool call: tell the model, let it retry
                    out = {"error": "BAD_ARGUMENTS", "detail": str(exc)}
                tool_ms = int((time.perf_counter() - t1) * 1000)
                session.log("tool_call", name=u.name, args=u.input, result=out, llm_ms=llm_ms,
                            ttft_ms=ttft_ms, tool_ms=tool_ms)
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": json.dumps(out)})
            messages.append({"role": "user", "content": results})
        return ""

    greeting = sc["greeting"]
    session.log("agent_says", text=greeting, llm_ms=0, scripted=True)
    t_lookup = time.perf_counter()
    out = session.lookup_customer(sc["caller_phone"])
    session.log("tool_call", name="lookup_customer", args={"phone": sc["caller_phone"]},
                result={"found": out["found"], "internal_only": True}, llm_ms=0,
                tool_ms=int((time.perf_counter() - t_lookup) * 1000), background=True)
    note = ("caller ID matches an existing customer record (details hidden from you)" if out["found"]
            else "caller ID matches NO customer record: treat as a new customer")
    messages.append({"role": "user", "content": f"[call connected; greeting already played; system note: {note}]"})
    messages.append({"role": "assistant", "content": greeting})
    turns.append({"speaker": "agent", "text": greeting})

    def sim_caller():
        first = sc["caller_name"].split()[0]
        transcript = "\n".join(f"{'Ava' if t['speaker'] == 'agent' else first}: "
                               f"{t.get('spoken_until_interrupt', t['text'])}" for t in turns)
        r = client.messages.create(model=model, max_tokens=120, thinking={"type": "disabled"},
                                   system=sc["caller_brief"], messages=[
            {"role": "user", "content": f"Call so far:\n{transcript}\n\nWrite {first}'s next line only."}])
        return "".join(b.text for b in r.content if b.type == "text").strip().strip('"')

    if "caller_brief" in sc:
        interrupt = dict(sc.get("interrupt") or {})
        line = {**sc["first_line"]}
        closing_exchange_done = False
        for _ in range(40):
            barge = False
            if interrupt and agent_last and interrupt["agent_contains"] in agent_last and (
                    "book" in agent_last.lower() or "right" in agent_last.lower()):
                idx = agent_last.find(interrupt["cut_after"])
                truncated = agent_last[: idx + len(interrupt["cut_after"])] + " and"
                session.log("barge_in", agent_text_spoken=truncated, agent_text_planned=agent_last)
                messages[-1] = {"role": "assistant", "content": truncated + " [caller interrupted]"}
                turns[-1]["spoken_until_interrupt"] = truncated
                line = {"text": interrupt["caller_says"]}
                interrupt = None
                barge = True
            if line["text"].startswith("[HANGUP]"):
                break
            session.on_caller_turn(line["text"], barge_in=barge)
            if line.get("asr_flag"):
                session.set_asr_flag(*line["asr_flag"])
            session.log("caller_says", text=line["text"], asr_note=line.get("asr_note"))
            turns.append({"speaker": "caller", "text": line["text"], "asr_note": line.get("asr_note")})
            user_text = line["text"] + (f"\n[ASR note: {line['asr_note']}]" if line.get("asr_note") else "")
            f = session.asr_flag
            if f and not f["resolved"]:
                user_text += (f"\n[System reminder: '{f['term']}' is still unconfirmed. Before you read the booking "
                              f"back, ask the caller once whether they meant '{f['alternative']}'.]")
            turns.append({"speaker": "agent", "text": agent_turn(user_text)})
            if session.transferred:
                break
            if session.call_id in session.db["calls"]:
                said_bye = re.search(r"(good day|goodbye|take care|thanks for calling|have a great)", agent_last, re.I)
                if said_bye or closing_exchange_done:
                    break
                closing_exchange_done = True  # agent finalized early: allow one last exchange for the goodbye
            line = {"text": sim_caller()}
            if os.environ.get("CONFIRM_PHRASE") and "is that right" in agent_last.lower():
                line = {"text": os.environ["CONFIRM_PHRASE"]}  # test hook: an unusual way of saying yes
        sc = {**sc, "caller_lines": []}

    for line in sc.get("caller_lines", []):
        barge = line.get("barge_in_after")
        if barge and agent_last:
            idx = agent_last.find(barge)
            truncated = agent_last[: idx + len(barge)] + " and"
            session.log("barge_in", agent_text_spoken=truncated, agent_text_planned=agent_last)
            messages[-1] = {"role": "assistant", "content": truncated + " [caller interrupted]"}
            turns[-1]["spoken_until_interrupt"] = truncated
            session.on_caller_turn(line["text"], barge_in=True)
        else:
            session.on_caller_turn(line["text"])
        session.log("caller_says", text=line["text"], asr_note=line.get("asr_note"))
        turns.append({"speaker": "caller", "text": line["text"], "asr_note": line.get("asr_note")})
        user_text = line["text"] + (f"\n[ASR note: {line['asr_note']}]" if line.get("asr_note") else "")
        turns.append({"speaker": "agent", "text": agent_turn(user_text)})

    if session.call_id not in session.db["calls"]:
        res = session.finalize_call("booked" if session.db["jobs"] else "info_only", "auto-finalized by orchestrator")
        session.log("tool_call", name="finalize_call", args={"auto": True}, result=res, llm_ms=0, tool_ms=0)

    result = {"scenario": scenario_name, "model": model, "caller_voice": sc.get("caller_voice"),
              "caller_name": sc.get("caller_name"), "turns": turns, "events": session.trace,
              "db_before": session.before, "db_after": session.db}
    os.makedirs(os.path.join(ROOT, "traces"), exist_ok=True)
    path = os.path.join(ROOT, "traces", f"{scenario_name}.json")
    os.makedirs(os.path.join(ROOT, "traces", "runs"), exist_ok=True)
    for p in (path, os.path.join(ROOT, "traces", "runs", f"{scenario_name}_{int(time.time())}.json")):
        with open(p, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
    return path, result


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "maria_main"
    mdl = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MODEL
    p, r = run(name, mdl)
    for t in r["turns"]:
        print(f"{t['speaker'].upper():6}: {t['text']}")
    print("\nEVENTS:")
    for e in r["events"]:
        if e["kind"] in ("tool_call", "write_blocked", "barge_in", "confirmation_given",
                         "pending_confirmation_discarded"):
            print(" ", e["kind"], e.get("name", ""), json.dumps(e.get("args", e.get("reason", "")))[:150])
    print("\nsaved", p)
