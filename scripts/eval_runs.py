"""Run a scenario N times and score each run against the acceptance criteria.

Usage: python scripts/eval_runs.py tony_sim 3
Prints a pass/fail table and saves traces/eval_<scenario>.json. Each run is also kept in traces/runs/.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agent"))
import agent_claude  # noqa: E402


def calls(r, name):
    return [e for e in r["events"] if e["kind"] == "tool_call" and e["name"] == name]


def criteria_tony(r):
    a, b = r["db_after"], r["db_before"]
    jobs = list(a["jobs"].values())
    job = jobs[0] if jobs else {}
    last = [t for t in r["turns"] if t["speaker"] == "agent"][-1]["text"]
    return {
        "safety questions asked and recorded": bool(calls(r, "record_triage")),
        "service area checked": bool(calls(r, "check_service_area")),
        "exactly one booking written": len(jobs) == 1,
        "new customer + property created": len(a["customers"]) == len(b["customers"]) + 1 and
                                           len(a["properties"]) == len(b["properties"]) + 1,
        "service type is Repair Service": job.get("category") == "Repair Service",
        "work notes name shingles and flashing": bool(re.search(r"shingle", job.get("notes", ""), re.I)) and
                                                 bool(re.search(r"flashing", job.get("notes", ""), re.I)),
        "access note about the dog saved": bool(re.search(r"dog", job.get("access_notes", ""), re.I)),
        "preferred slot honoured (Tue 24 Nov, 13:00)": job.get("start") == "2026-11-24 13:00",
        "text sent only after consent": len(a["sms"]) == 1,
        "no stray cases created": len(a["cases"]) == 0,
        "call logged": bool(a["calls"]),
        "ends with a goodbye": bool(re.search(r"(good day|goodbye|great day|good one|see you|take care)", last, re.I)),
    }


def criteria_maria(r):
    a = r["db_after"]
    jobs = list(a["jobs"].values())
    job = jobs[0] if jobs else {}
    slots = {s["slot_id"]: s["available"] for s in a["slots"]}
    return {
        "safety questions asked and recorded": bool(calls(r, "record_triage")),
        "interruption discarded the pending 10:30 read-back": any(
            e["kind"] == "pending_confirmation_discarded" and e.get("reason") == "caller_interrupted"
            for e in r["events"]),
        "exactly one booking, at 9:00": len(jobs) == 1 and job.get("start") == "2026-11-20 09:00",
        "10:30 slot untouched": slots.get("S-2001030") is True,
        "term corrected to 'valley metal'": "valley metal" in job.get("notes", "").lower() and
                                            "valley matter" not in job.get("notes", "").lower(),
        "priority urgent for the active leak": job.get("priority") == "Urgent",
        "separate high-priority case for the nails": any(c["priority"] == "high" for c in a["cases"].values()),
        "text sent only after consent": len(a["sms"]) == 1,
        "call logged": bool(a["calls"]),
    }


def criteria_emergency(r):
    a = r["db_after"]
    cases = list(a["cases"].values())
    texts = " ".join(t["text"] for t in r["turns"] if t["speaker"] == "agent").lower()
    return {
        "three safety questions asked and answers recorded": bool(calls(r, "record_triage")),
        "transferred to a human": bool(calls(r, "transfer_to_human")),
        "no booking and no job created": len(a["jobs"]) == 0 and not calls(r, "create_inspection_booking"),
        "urgent case with the caller's own words": any(c["priority"] == "urgent" and "sagging" in c["note"].lower()
                                                       for c in cases),
        "said it is urgent and mentioned 911": "urgent" in texts and "911" in texts,
        "call logged": bool(a["calls"]),
        "no text message sent": len(a["sms"]) == 0,
    }


def criteria_outside(r):
    a = r["db_after"]
    cases = list(a["cases"].values())
    offered = [e for e in r["events"] if e["kind"] == "tool_call" and e["name"] == "get_availability"]
    texts = " ".join(t["text"] for t in r["turns"] if t["speaker"] == "agent").lower()
    return {
        "service area checked": bool(calls(r, "check_service_area")),
        "told the caller kindly it is outside the area": bool(re.search(r"(outside|not in|don.t serve|do not serve|"
                                                                          r"beyond) .*(area|serve)|service area", texts)),
        "no slot offered or booked": len(a["jobs"]) == 0 and not offered,
        "callback task created": any(c["type"] in ("callback", "outside_service_area") or "callback" in c["note"].lower()
                                     for c in cases),
        "call logged": bool(a["calls"]),
        "ends with a goodbye": bool(re.search(r"(good day|goodbye|great day|take care|have a)", texts[-200:], re.I)),
    }


CHECKS = {"tony_sim": criteria_tony, "maria_sim": criteria_maria, "emergency_sim": criteria_emergency,
          "outside_sim": criteria_outside}

if __name__ == "__main__":
    name, n = sys.argv[1], int(sys.argv[2])
    rows = []
    for i in range(n):
        path, r = agent_claude.run(name)
        res = CHECKS[name](r)
        says = [e for e in r["events"] if e["kind"] == "agent_says" and not e.get("scripted")]
        ttft = sorted(e["ttft_ms"] for e in says)
        rows.append({"run": i + 1, "passed": sum(res.values()), "total": len(res), "results": res,
                     "ttft_median_ms": ttft[len(ttft) // 2], "turns": len(says)})
        print(f"run {i + 1}: {sum(res.values())}/{len(res)}  failed: {[k for k, v in res.items() if not v]}")
        # keep each run's trace under its own name too
        os.replace(path, os.path.join(ROOT, "traces", "runs", f"{name}_eval{i + 1}.json"))
    json.dump(rows, open(os.path.join(ROOT, "traces", f"eval_{name}.json"), "w"), indent=1)
