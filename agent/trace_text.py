"""Plain-English wording for tool calls and safety checks, shared by the live agent and the recorded-call page."""
import datetime as dt

TOOL_TITLES = {
    "lookup_customer": "Looked up the caller by phone number",
    "match_property": "Matched the address the caller said to the properties on file",
    "check_service_area": "Checked whether the address is inside the service area",
    "get_availability": "Checked open times in the schedule",
    "record_triage": "Recorded the answers to the three safety questions",
    "read_back": "Prepared the details to read back (nothing is saved yet)",
    "create_inspection_booking": "SAVED: created the service request and the job",
    "send_sms": "SAVED: sent the confirmation text",
    "create_case": "SAVED: created a follow-up case for the office",
    "transfer_to_human": "Transferred the call to the office team",
    "finalize_call": "SAVED: wrote the call log",
}
WRITES = {"create_inspection_booking", "send_sms", "create_case", "finalize_call"}


def tool_result_text(name, args, res):
    if "error" in res:
        return f"Blocked: {res['error']}" + (f" ({', '.join(res['missing'])})" if res.get("missing") else "")
    if name == "lookup_customer":
        return "Customer found (details held back from the agent)" if res.get("found") else "No customer on file: treated as a new customer"
    if name == "match_property":
        return f"Matched {res['address']}, {res['city']}" if res.get("matched") else "No match"
    if name == "check_service_area":
        return "Inside the service area" if res.get("in_service_area") else "Outside the service area"
    if name == "get_availability":
        av = res.get("available", [])
        days = {}
        wd = lambda s: s.get("weekday") or dt.date.fromisoformat(s["date"]).strftime("%A")  # noqa: E731
        for s in av:
            days.setdefault(f"{wd(s)[:3]} {s['date'][5:]}", []).append(s["time"])
        taken = res.get("taken", [])
        t = "; ".join(f"{d}: {', '.join(ts)}" for d, ts in list(days.items())[:6])
        extra = f" | taken: {', '.join(wd(x)[:3] + ' ' + x['time'] for x in taken)}" if taken else ""
        return f"{len(av)} open slots. {t}{extra}"
    if name == "record_triage":
        return "Not an emergency" if res.get("decision") == "not_emergency" else "Unsafe answer: transfer to a person"
    if name == "read_back":
        return f"Pending confirmation {res.get('confirmation_id')} created"
    if name == "create_inspection_booking":
        extra = f", new customer {res['new_customer_id']}" if res.get("new_customer_id") else ""
        return f"Job {res['job_id']} and request {res['enquiry_id']} created for {res['start']}{extra}"
    if name == "send_sms":
        return f"Text {res['sms_id']} sent"
    if name == "create_case":
        return f"Case {res['case_id']} created, callback {res['callback']}"
    if name == "finalize_call":
        return f"Call log {res['call_id']} saved"
    if name == "transfer_to_human":
        return "Call handed to the office team"
    return str(res)[:120]


def gate_text(e):
    k = e["kind"]
    if k == "asr_low_confidence":
        return f"Recogniser was unsure about \"{e['term']}\". The agent must check \"{e['alternative']}\" with the caller first."
    if k == "asr_term_resolved":
        return f"The caller's reply settled the unclear term \"{e['term']}\"."
    if k == "triage_required":
        return "The caller mentioned storm or leak words, so the three safety questions are now mandatory before any booking."
    if k == "confirmation_given":
        return f"Caller said yes. Confirmation {e['confirmation_id']} approved: only what was read back can be saved."
    if k == "pending_confirmation_discarded":
        why = {"caller_interrupted": "the caller interrupted", "not_affirmed": "the caller did not say yes"}.get(e["reason"], e["reason"])
        return f"Pending confirmation {', '.join(e['ids'])} thrown away because {why}. Nothing was saved."
    if k == "read_back_blocked":
        r = e["reason"]
        return {"unresolved_low_confidence_term": f"Blocked: \"{e.get('term')}\" is still unconfirmed. The agent must ask the caller first.",
                "safety_questions_not_asked": "Blocked: the safety questions have not been asked yet.",
                "incomplete_record": f"Blocked: the record is missing {', '.join(e.get('missing', []))}."}.get(r, r)
    if k == "triage_rejected":
        return "Blocked: the safety answers were not backed by anything the caller actually said."
    if k == "write_blocked":
        return "Blocked: tried to save before the caller confirmed."
    return k


def records_diff(before, after):
    """What changed between two snapshots of the mock records, in display order."""
    labels = {"customers": "Customer", "properties": "Property", "enquiries": "Service request", "jobs": "Job",
              "cases": "Case", "sms": "Text message", "calls": "Call log"}
    hide = {"idempotency_key"}
    changes = []
    for coll, label in labels.items():
        for key, val in after[coll].items():
            if key not in before[coll]:
                changes.append({"type": label, "id": key, "action": "Created",
                                "fields": {f: v for f, v in val.items() if f not in hide}})
            elif val != before[coll][key]:
                changes.append({"type": label, "id": key, "action": "Updated",
                                "fields": {f: {"before": before[coll][key].get(f), "after": v}
                                           for f, v in val.items() if before[coll][key].get(f) != v and f not in hide}})
    for s_after in after["slots"]:
        s_before = next(s for s in before["slots"] if s["slot_id"] == s_after["slot_id"])
        if s_before["available"] and not s_after["available"]:
            changes.append({"type": "Technician schedule", "id": s_after["slot_id"], "action": "Updated",
                            "fields": {"slot": f"{s_after['date']} {s_after['time']}",
                                       "availability": {"before": "Open", "after": "Held for the job"}}})
    rank = {"Customer": 0, "Property": 1, "Service request": 2, "Job": 3, "Technician schedule": 4,
            "Text message": 5, "Case": 6, "Call log": 7}
    changes.sort(key=lambda z: rank.get(z["type"], 9))
    return changes
