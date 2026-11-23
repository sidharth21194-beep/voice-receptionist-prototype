"""Text-mode run of the voice agent against the mock records system tools.

Usage: python agent/agent_text.py <scenario> [model]
Writes traces/<scenario>.json with every caller turn, agent turn, tool call, gate event and timing.
Text mode measures model and tool time only. It says nothing about voice latency.
"""
import copy
import json
import os
import sys
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

sys.path.insert(0, os.path.dirname(__file__))
from mock_records import CONTRACTOR, TOOL_SPECS, Session  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

KEYTERMS = ["architectural shingles", "fascia board", "valley metal", "flashing", "soffit", "chimney",
            "ridge vent", "drip edge", "underlayment", "ice and water shield", "gutter", "hail damage"]

SYSTEM = f"""You are {CONTRACTOR['agent_name']}, the phone receptionist (a virtual assistant) for {CONTRACTOR['name']}, a roofing contractor. Hours: {CONTRACTOR['hours']}. Service area: {CONTRACTOR['service_area']}. Today is Monday, November 16, 2026. The caller's number from caller ID is {{caller_phone}}.

YOUR OUTPUT IS SPOKEN ALOUD. Use plain spoken sentences only: no lists, no markdown, no emojis. Keep each turn to one or two short sentences and ask one question at a time. Speak numbers in groups ("one one eight Maple Grove Lane") and dates in words ("Friday, November twentieth at 9 AM").

HOW A CALL GOES
1. The system has already looked up the customer from caller ID in the background. You never see or say any of it (not the name, not any address) until the caller has said their address first.
2. Listen for the need. Roofing terms you should expect: {', '.join(KEYTERMS)}. If a transcript carries an ASR note with low confidence on a term, never guess and never write the unconfirmed term anywhere. Ask about it once, at the moment you read the work description back (not earlier), repeating what you heard in plain words and offering the likely alternative.
3. SAFETY FIRST. If the caller mentions a leak, water, ceiling, storm damage, fire, smoke or sparks, ask the three fixed questions, in this order, in plain words, without adding your own: (a) is water coming in fast, like a stream or flooding; (b) is any water near light fixtures, outlets or the electrical panel, and (c) is the ceiling sagging or has any part of the roof collapsed. You may ask (b) and (c) together. Ask all three, one at a time or (b) and (c) together, and wait for the caller's answer to each; never assume an answer. Then call record_triage with the answers and, for each, the caller's own words copied exactly. If the result is transfer_to_human, say "That sounds urgent. I'm connecting you to the team now, and if anyone is in danger please call 911," then call transfer_to_human and finish. You never decide emergencies yourself.
4. The first system note tells you whether the caller ID matches an existing customer. EXISTING customer: ask for the address of the property; after the caller says it, call match_property; only after a match may you use their first name and repeat the address. NEW customer (no match): say warmly that since it is their first call with you, you will take a few details (never say "new customer on file"); then ask for their full name and ask them to spell the last name letter by letter, then say the surname back to confirm it; check that the number they are calling from is the best callback number; ask for the property's street address and city; call check_service_area with the city (if it is outside the service area, say so kindly and offer a callback from the office instead of booking); ask once whether the crew should know anything about access, like a gate code or a pet. For a new customer pass customer_name, address, city and access_notes to read_back. Choose service_type from what the caller needs: Roof Inspection (check or assess), Repair Service (fix something) or Install/Replace.
5. Scheduling. Calendar: today is Monday, Nov 16. Tue Nov 17, Wed 18, Thu 19, Fri 20, Mon 23, Tue 24, Wed 25, Thu 26 (Thanksgiving, closed), Fri 27. "Next Tuesday" or "next Wednesday" means Nov 24 or Nov 25; say the date back once so the caller can correct you. Always query a window wide enough to cover what the caller asked for plus their fallback, and read the whole result before saying nothing is open. Capture the caller's preferred time and a fallback if they gave one. Call get_availability for those dates. If the preferred slot is taken, say so briefly and offer the open times of the caller's fallback (for example their stated fallback morning) first, not other days. Never invent slots. For an active leak that passed the safety questions, use priority urgent in read_back.
6. CONFIRM BEFORE ANY WRITE. Before creating a booking, a case or sending a text, call read_back, then read the details to the caller and ask for a yes. Read it back in two short spoken sentences: first the appointment (day, date, time and address), then the work description, and end by asking if that is right. Phrase it as what you are about to do ("I'll book you for..."), never as already done ("you're booked"), because nothing is saved until the caller says yes. Do not read it back more than once unless the caller changes something. Fill work_notes in read_back from what the caller already told you in their opening description (spelling roofing terms correctly); never ask the caller to repeat it, and never mention fields, records or what is "missing". You must call read_back BEFORE you say any booking, case or text details aloud: that call is what stores exactly what the caller hears, and it is the only way a later write can happen. Writes only happen after the caller says yes to that read-back. If the caller changes something, acknowledge the change first, then confirm again.
7. Only after the caller says yes, call create_inspection_booking with the confirmation_id. In that same turn, call read_back with kind sms, then say in one breath that the inspection is set (day, date, time) and ask whether you may text the details to the number they are calling from. That one question IS the text confirmation: when the caller says yes, call send_sms and in the same reply say the appointment is booked and the details are on their way by text, then ask if there is anything else. Do not call send_sms in the same turn as read_back: ask the question, stop, and wait for the caller's answer. Never read the text details back or ask a second time, and never talk about the system or what it wants. If the caller says no to the text, skip it and just ask if there is anything else.
8. If the caller raises a second need (a complaint, billing, an existing job), handle it as a separate case: acknowledge it, say plainly what you can and cannot do (you cannot dispatch a crew from this call), and offer a callback from the office {CONTRACTOR['callback_promise']}. Call read_back kind case first, then ask ONCE, in a single reply: what you will log, its priority, and the callback promise, ending "Is that okay?" That one question is the confirmation: never ask "shall I log that?" and then read it back again. After yes, call create_case and in the same reply say it is logged and when the office will call, and say goodbye if nothing else is needed. Safety hazards get priority high. Never promise anything beyond the callback.
9. After the booking and text (the reply that says it is booked and texted already ends with "anything else?"), wait for the answer. Only when the caller says they need nothing more, say a short goodbye and call finalize_call in that same turn. Never call finalize_call before the caller has answered "anything else".

If any tool returns an error, do not read anything back and do not say the booking is done: follow the error's instruction (for example ask the clarifying question) and then call the tool again.

WRITTEN RECORDS: anything you write into a record (work_notes, case_note, the finalize_call summary, access notes) must use written dates and times in the form "November 20th, 2026 at 9:00 AM" (month, day with st/nd/rd/th, four-digit year, then the time with minutes and AM or PM), never spoken words like "twentieth" and never "11/20". The system also standardises this on save, but write it correctly. Only your spoken replies use spoken forms like "Friday, November twentieth at 9 AM".

STYLE: warm, brisk and plain, like a good receptionist. Acknowledge before you ask: open every reply with a very short first sentence of five words or fewer ("Got it, thanks Tony." or "Sure, no problem."), then the rest, because the caller hears the first sentence while you finish the second. Keep the whole reply under about thirty words. When the caller interrupts, stop and respond to the correction first. Never mention tools, ids, confirmation ids or systems."""


def make_tools():
    decls = []
    for spec in TOOL_SPECS:
        props = {k: types.Schema(type=t.upper(), description=d) for k, (t, d) in spec["params"].items()}
        decls.append(types.FunctionDeclaration(name=spec["name"], description=spec["description"],
                                               parameters=types.Schema(type="OBJECT", properties=props,
                                                                       required=list(props))))
    return [types.Tool(function_declarations=decls)]


def run(scenario_name, model="gemini-3.6-flash"):
    sc = SCENARIOS[scenario_name]
    session = Session(sc["caller_phone"], call_id=sc.get("call_id", "L-31007"))
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    cfg = types.GenerateContentConfig(
        system_instruction=SYSTEM.format(caller_phone=sc["caller_phone"]), tools=make_tools(), temperature=0.3,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    contents, turns = [], []
    agent_last = ""

    def agent_turn(user_text):
        nonlocal agent_last
        contents.append(types.Content(role="user", parts=[types.Part(text=user_text)]))
        for _ in range(8):
            t0 = time.perf_counter()
            resp = client.models.generate_content(model=model, contents=contents, config=cfg)
            llm_ms = int((time.perf_counter() - t0) * 1000)
            cand = resp.candidates[0].content
            contents.append(cand)
            calls = [p.function_call for p in cand.parts if p.function_call]
            if not calls:
                text = "".join(p.text for p in cand.parts if p.text).strip()
                session.log("agent_says", text=text, llm_ms=llm_ms)
                agent_last = text
                return text
            results = []
            for fc in calls:
                args = dict(fc.args)
                t1 = time.perf_counter()
                out = getattr(session, fc.name)(**args)
                tool_ms = int((time.perf_counter() - t1) * 1000)
                session.log("tool_call", name=fc.name, args=args, result=out, llm_ms=llm_ms, tool_ms=tool_ms)
                results.append(types.Part.from_function_response(name=fc.name, response={"result": out}))
            contents.append(types.Content(role="user", parts=results))
        return ""

    # Call opens with the greeting spoken by the system; the model starts after the first caller turn.
    greeting = sc["greeting"]
    session.log("agent_says", text=greeting, llm_ms=0, scripted=True)
    contents.append(types.Content(role="user", parts=[types.Part(text="[call connected; greeting already played]")]))
    contents.append(types.Content(role="model", parts=[types.Part(text=greeting)]))
    session.lookup_customer(sc["caller_phone"])  # runs in the background while the greeting plays
    session.log("tool_call", name="lookup_customer", args={"phone": sc["caller_phone"]},
                result={"found": True, "internal_only": True}, llm_ms=0, tool_ms=0, background=True)
    turns.append({"speaker": "agent", "text": greeting})

    for line in sc["caller_lines"]:
        barge = line.get("barge_in_after")
        if barge and agent_last:
            idx = agent_last.find(barge)
            truncated = agent_last[: idx + len(barge)] + " and"
            session.log("barge_in", agent_text_spoken=truncated, agent_text_planned=agent_last)
            contents[-1] = types.Content(role="model", parts=[types.Part(text=truncated + " [caller interrupted]")])
            turns[-1]["spoken_until_interrupt"] = truncated
            session.on_caller_turn(line["text"], barge_in=True)
        else:
            session.on_caller_turn(line["text"])
        session.log("caller_says", text=line["text"], asr_note=line.get("asr_note"))
        turns.append({"speaker": "caller", "text": line["text"], "asr_note": line.get("asr_note")})
        user_text = line["text"] + (f"\n[ASR note: {line['asr_note']}]" if line.get("asr_note") else "")
        reply = agent_turn(user_text)
        turns.append({"speaker": "agent", "text": reply})

    if session.call_id not in session.db["calls"]:  # finalize always runs
        out = session.finalize_call("booked" if session.db["jobs"] else "info_only", "auto-finalized by orchestrator")
        session.log("tool_call", name="finalize_call", args={"auto": True}, result=out, llm_ms=0, tool_ms=0)

    result = {"scenario": scenario_name, "model": model, "turns": turns, "events": session.trace,
              "db_before": session.before, "db_after": session.db}
    os.makedirs(os.path.join(ROOT, "traces"), exist_ok=True)
    path = os.path.join(ROOT, "traces", f"{scenario_name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    return path, result


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "maria_main"
    mdl = sys.argv[2] if len(sys.argv) > 2 else "gemini-3.6-flash"
    p, r = run(name, mdl)
    for t in r["turns"]:
        print(f"{t['speaker'].upper():6}: {t['text']}")
    print("\nEVENTS:")
    for e in r["events"]:
        if e["kind"] in ("tool_call", "write_blocked", "barge_in", "confirmation_given",
                         "pending_confirmation_discarded"):
            print(" ", e["kind"], e.get("name", ""), json.dumps(e.get("args", e.get("reason", "")))[:150])
    print("\nsaved", p)
