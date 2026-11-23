"""Mock field-service records and tools (fictional data, invented API).

Design rule that the whole prototype demonstrates: a write tool never takes the
model's free-text arguments. It takes a confirmation_id, and writes exactly the
details the caller heard in the read-back and said "yes" to. If the caller
interrupts or changes anything, the pending confirmation is discarded.
"""
import copy
import datetime as dt
import itertools
import re

_ONES = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth", "eleventh",
         "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth", "nineteenth",
         "twentieth"]
ORD_WORDS = {w: i + 1 for i, w in enumerate(_ONES)}
for _i, _w in enumerate(_ONES[:9]):  # twenty-first ... twenty-ninth, thirty-first style forms
    ORD_WORDS[f"twenty-{_w}"] = 21 + _i
    ORD_WORDS[f"twenty {_w}"] = 21 + _i
ORD_WORDS.update({"thirtieth": 30, "thirty-first": 31, "thirty first": 31})
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_ORD_RE = "|".join(sorted((re.escape(w) for w in ORD_WORDS), key=len, reverse=True))
_DATE_RE = re.compile(
    rf"(?P<wd>(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?(?P<mo>{_MONTHS})\s+"
    rf"(?:(?P<dw>{_ORD_RE})|(?P<dn>\d{{1,2}})(?:st|nd|rd|th)?)(?:,?\s+(?P<yr>\d{{4}}))?"
    rf"(?:,?\s*(?:at\s+)?(?P<hr>\d{{1,2}}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    rf"(?::(?P<mi>\d{{2}}))?\s*(?P<ap>[AaPp]\.?[Mm]\.?))?", re.I)
HOUR_WORDS = {w: i + 1 for i, w in enumerate("one two three four five six seven eight nine ten eleven twelve".split())}
YEAR = 2026


def ordinal(n: int) -> str:
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def normalize_dates(text: str) -> str:
    """Write dates and times in saved records as 'November 20th, 2026 at 9:00 AM', never as spoken words."""
    if not isinstance(text, str):
        return text

    def sub(m):
        day = ORD_WORDS.get((m.group("dw") or "").lower()) or int(m.group("dn"))
        out = (m.group("wd") or "").replace(" ,", ",")
        out += f"{m.group('mo').capitalize()} {ordinal(day)}, {m.group('yr') or YEAR}"
        if m.group("hr"):
            ap = m.group("ap").replace(".", "").upper()
            hr = m.group("hr").lower()
            out += f" at {HOUR_WORDS.get(hr) or int(hr)}:{m.group('mi') or '00'} {ap}"
        return out

    return _DATE_RE.sub(sub, text)


def written_datetime(date_iso: str, hhmm: str) -> str:
    d = dt.date.fromisoformat(date_iso)
    h, mi = int(hhmm[:2]), hhmm[3:5]
    return f"{d.strftime('%B')} {ordinal(d.day)}, {d.year} at {h % 12 or 12}:{mi} {'AM' if h < 12 else 'PM'}"


CONTRACTOR = {
    "name": "Ridgeline Roofing",
    "agent_name": "Ava",
    "hours": "Mon-Fri 8 AM to 5 PM",
    "service_area": "King and Snohomish counties, WA",
    "callback_promise": "same business day",
    "services": ["Roof Inspection", "Repair Service", "Install/Replace"],
}

_YES_WORDS = re.compile(r"\b(yes|yeah|yep|yup|yea|correct|right|exactly|sure|ok|okay|go ahead|sounds good|that works|"
                        r"perfect|please|do it|absolutely|definitely|fine|good|great)\b", re.I)
_NOT_A_YES = re.compile(r"^\s*(no|nope|nah|wait|hold on|not)\b|\b(change|instead|actually|but|however|wrong|incorrect|"
                        r"not right|isn't right|isn't correct|don't)\b", re.I)


_STARTS_YES = re.compile(r"^\W*(yes|yeah|yep|yup|yea|correct|that's right|that is right|you're right|you are right|"
                         r"exactly|sure|ok|okay|go ahead|sounds good|that works|perfect|please do|absolutely|definitely)\b",
                         re.I)


class _Affirm:
    """True for a spoken yes: a reply that starts with a clear yes ("Yes, thank you, and one more thing"), or a short
    reply that contains one ("You're right", "Sounds good, thanks"). False when it starts with a no or carries a
    correction ("yes, but make it 3 PM")."""

    @staticmethod
    def match(text):
        t = text or ""
        if _NOT_A_YES.search(t):
            return False
        if _STARTS_YES.match(t):
            return True
        return bool(_YES_WORDS.search(t)) and len(t.split()) <= 8


AFFIRM = _Affirm()

DANGER_WORDS = re.compile(r"\b(fire|smoke|sparks?|collapse[ds]?|electrocut\w*)\b", re.I)
TRIAGE_TRIGGER = re.compile(r"\b(leak\w*|water|drip\w*|ceiling|storm|flood\w*|fire|smoke|sparks?|collaps\w*|"
                            r"emergency|hail)\b", re.I)


def initial_db():
    def slot(sid, day, hhmm, available=True):
        return {"slot_id": sid, "date": day, "time": hhmm, "tech": "T-12" if hhmm < "12:00" else "T-07",
                "available": available}

    return {
        "customers": {
            "C-2041": {"name": "Maria Lopez", "phone": "+15550142", "properties": ["P-77", "P-81"],
                       "last_contact": None, "notes": []},
            "C-2102": {"name": "Sam Carter", "phone": "+15550199", "properties": ["P-90"],
                       "last_contact": None, "notes": []},
        },
        "properties": {
            "P-77": {"customer": "C-2041", "address": "118 Maple Grove Lane", "city": "Kenmore, WA"},
            "P-81": {"customer": "C-2041", "address": "19 Maple Court", "city": "Bothell, WA"},
            "P-90": {"customer": "C-2102", "address": "318 Cedar Ridge Drive", "city": "Everett, WA"},
        },
        "slots": [
            slot("S-1900900", "2026-11-19", "09:00"), slot("S-1901100", "2026-11-19", "11:00"),
            slot("S-1901400", "2026-11-19", "14:00", available=False),
            slot("S-1901600", "2026-11-19", "16:00"),
            slot("S-2000900", "2026-11-20", "09:00"), slot("S-2001030", "2026-11-20", "10:30"),
            slot("S-2001300", "2026-11-20", "13:00"),
            slot("S-2300900", "2026-11-23", "09:00"), slot("S-2301400", "2026-11-23", "14:00"),
            slot("S-2401300", "2026-11-24", "13:00"), slot("S-2401500", "2026-11-24", "15:00"),
            slot("S-2500900", "2026-11-25", "09:00"), slot("S-2501030", "2026-11-25", "10:30"),
        ],
        "enquiries": {}, "jobs": {}, "cases": {}, "calls": {}, "sms": {},
    }


class Session:
    """One call. Holds the confirm-before-write gate and the trace."""

    def __init__(self, caller_phone, db=None, call_id="L-31007", id_base=0):
        self.id_base = id_base
        self.db = db if db is not None else initial_db()
        self.caller_phone = caller_phone
        self.call_id = call_id
        self.candidates = []
        self.property_id = None
        self.customer_id = None
        self.pending = {}          # confirmation_id -> details
        self.confirmed = set()
        self.last_pending_id = None
        self.triage = None
        self.triage_words = {}
        self.caller_turns = []
        self.triage_required = False
        self.transferred = False
        self.asr_flag = None       # low-confidence term that must be clarified before any read-back
        self.trace = []            # ordered events for the deck and the records screen
        self._ids = itertools.count(1)
        self.before = copy.deepcopy(self.db)

    # ---- event log -------------------------------------------------
    def log(self, kind, **data):
        self.trace.append({"kind": kind, **data})

    # ---- caller-turn hooks (called by the orchestrator, not the model) ----
    def set_asr_flag(self, term, alternative):
        """The speech recogniser reported low confidence on a term. Set by the orchestrator, not the model."""
        self.asr_flag = {"term": term, "alternative": alternative, "asked": False, "resolved": False}
        self.log("asr_low_confidence", term=term, alternative=alternative)

    def on_caller_turn(self, text, barge_in=False):
        """Called for every caller utterance before the model sees it."""
        if not barge_in:
            self.caller_turns.append(text)
        if TRIAGE_TRIGGER.search(text) and not self.triage_required:
            self.triage_required = True
            self.log("triage_required", reason="caller mentioned water, leak, storm or safety words", text=text[:80])
        f = self.asr_flag
        if f and not f["resolved"] and not barge_in and (f["asked"] or f["alternative"] in text.lower()):
            f["resolved"] = True
            self.log("asr_term_resolved", term=self.asr_flag["term"], caller_said=text)
        if barge_in:
            if self.pending:
                self.log("pending_confirmation_discarded", ids=list(self.pending), reason="caller_interrupted")
            self.pending.clear()
            self.last_pending_id = None
            return
        if self.last_pending_id and self.last_pending_id in self.pending:
            if AFFIRM.match(text):
                self.confirmed.add(self.last_pending_id)
                self.log("confirmation_given", confirmation_id=self.last_pending_id, caller_said=text)
            else:
                self.log("pending_confirmation_discarded", ids=[self.last_pending_id], reason="not_affirmed",
                         caller_said=text)
                del self.pending[self.last_pending_id]
            self.last_pending_id = None

    # ---- tools (read) -----------------------------------------------
    def lookup_customer(self, phone: str):
        """Look up customer candidates by the caller's phone number. Result is internal: never read it aloud."""
        found = [c for c in self.db["customers"].items() if c[1]["phone"] == phone]
        self.candidates = []
        for cid, c in found:
            self.customer_id = cid
            for pid in c["properties"]:
                self.candidates.append(pid)
        return {"found": bool(found), "customer_id": self.customer_id,
                "property_ids": self.candidates, "internal_only": True}

    def match_property(self, address_spoken: str):
        """Match the address the caller said to the customer's properties. Returns the match or none."""
        norm = " ".join(re.sub(r"[^a-z0-9]", " ", address_spoken.lower()).split())
        words = {"forty": "4", "seven": "7", "two": "2", "three": "3", "eighteen": "18", "nineteen": "19"}
        for pid in self.candidates:
            street = self.db["properties"][pid]["address"].lower()
            num = street.split()[0]
            name_tokens = [t for t in street.split()[1:] if len(t) > 3]
            if any(t in norm for t in name_tokens) and (num in norm or num in norm.replace(" ", "")
                                                        or self._spoken_matches(num, norm)):
                self.property_id = pid
                p = self.db["properties"][pid]
                return {"matched": True, "property_id": pid, "address": p["address"], "city": p["city"],
                        "customer_name": self.db["customers"][p["customer"]]["name"].split()[0]}
        return {"matched": False}

    @staticmethod
    def _spoken_matches(num, norm):
        spoken = {"118": ["one eighteen", "one one eight", "118"], "19": ["nineteen", "one nine", "19"],
                  "318": ["three eighteen", "three one eight", "318"]}
        return any(s in norm for s in spoken.get(num, []))

    def check_service_area(self, city: str):
        """Check whether the contractor serves the city the caller gave (for a new customer's address)."""
        served = {"everett", "bothell", "kenmore", "lynnwood", "seattle", "mukilteo", "kirkland", "woodinville"}
        ok = city.strip().lower().split(",")[0] in served
        return {"city": city, "in_service_area": ok, "service_area": CONTRACTOR["service_area"]}

    def get_availability(self, date_from: str, date_to: str):
        """List inspection slots between two dates (YYYY-MM-DD). Includes which requested slots are taken."""
        slots = [s for s in self.db["slots"] if date_from <= s["date"] <= date_to]

        def fmt(s):
            wd = dt.date.fromisoformat(s["date"]).strftime("%A")
            return {"slot_id": s["slot_id"], "weekday": wd, "date": s["date"], "time": s["time"]}

        return {"available": [fmt(s) for s in slots if s["available"]],
                "taken": [fmt(s) for s in slots if not s["available"]],
                "note": "Slots are listed by weekday and date. Offer only slots from this list."}

    def record_triage(self, water_fast: bool, near_electrical: bool, ceiling_sagging: bool,
                      water_fast_words: str, electrical_words: str, ceiling_words: str,
                      other_danger: bool = False):
        """Record the caller's answers to the three fixed safety questions. For each answer also pass the caller's
        own words that answered it (copied exactly from what the caller said). The decision is made by code,
        and answers the caller never gave are rejected."""
        heard = " ".join(self.caller_turns).lower()
        norm = lambda s: " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())  # noqa: E731
        heard_n = norm(heard)
        bad = [name for name, words in (("water_fast_words", water_fast_words),
                                        ("electrical_words", electrical_words),
                                        ("ceiling_words", ceiling_words))
               if not words.strip() or norm(words) not in heard_n]
        if bad:
            self.log("triage_rejected", reason="answers_not_heard_from_caller", fields=bad)
            return {"error": "TRIAGE_ANSWERS_NOT_HEARD", "fields": bad,
                    "instruction": "Ask the caller each safety question, wait for the answer, then pass the caller's "
                                   "own words. Never fill in an answer the caller did not give."}
        unsafe = water_fast or near_electrical or ceiling_sagging or other_danger
        self.triage = {"decision": "transfer_to_human" if unsafe else "not_emergency"}
        if unsafe:
            self.triage["say_exactly"] = ("That sounds urgent. I'm connecting you to the team now, and if anyone is in "
                                          "danger please call 911.")
        self.triage_words = {"water coming in fast": water_fast_words, "water near electrics": electrical_words,
                             "ceiling": ceiling_words}
        return self.triage

    # ---- confirmation gate -------------------------------------------
    def read_back(self, kind: str, summary: str, slot_id: str = "", work_notes: str = "",
                  case_type: str = "", case_note: str = "", priority: str = "normal",
                  service_type: str = "Roof Inspection", customer_name: str = "", address: str = "",
                  city: str = "", access_notes: str = ""):
        """Call this immediately before you read details back to the caller for a yes/no. kind is one of
        booking, case, sms. Nothing is written until the caller says yes to this read-back. For a new customer
        also pass customer_name, address, city and any access_notes."""
        if kind == "booking" and (self.transferred or (self.triage or {}).get("decision") == "transfer_to_human"):
            self.log("read_back_blocked", reason="emergency_transfer_first")
            return {"error": "EMERGENCY_TRANSFER_FIRST",
                    "instruction": "The safety answers say this is urgent. Do not book. Say \"That sounds urgent. I'm "
                                   "connecting you to the team now, and if anyone is in danger please call 911\", then "
                                   "call transfer_to_human."}
        if kind == "booking" and self.triage_required and self.triage is None:
            self.log("read_back_blocked", reason="safety_questions_not_asked")
            return {"error": "TRIAGE_REQUIRED",
                    "instruction": "The caller mentioned water, a leak or storm damage. Ask the three fixed safety "
                                   "questions in plain words, then call record_triage, before anything else."}
        f = self.asr_flag
        if kind == "booking" and f and not f["resolved"]:
            f["asked"] = True
            self.log("read_back_blocked", reason="unresolved_low_confidence_term", term=f["term"])
            return {"error": "CLARIFY_TERM_FIRST",
                    "instruction": f"The recogniser was unsure about '{f['term']}'. Ask the caller once, in plain "
                                   f"words, whether they meant '{f['alternative']}'. Then call read_back again "
                                   "using the term the caller confirms."}
        if kind == "booking":
            missing = [k for k, v in (("slot_id", slot_id), ("work_notes", work_notes)) if not v]
            if self.property_id is None:  # unknown caller: the new customer's details are part of the record
                missing += [k for k, v in (("customer_name", customer_name), ("address", address),
                                           ("city", city)) if not v]
            if missing:
                self.log("read_back_blocked", reason="incomplete_record", missing=missing)
                return {"error": "INCOMPLETE_RECORD", "missing": missing,
                        "instruction": "Call read_back again right now and include these parameters, filled from what the caller "
                                       "already said (for work_notes: one short sentence describing the roofing work, "
                                       "e.g. 'Loose ridge shingles and lifting vent flashing after a storm'). "
                                       "Do not speak to the caller until read_back succeeds, and never mention missing details."}
        cid = f"CF-{next(self._ids)}"
        self.pending[cid] = {"kind": kind, "summary": summary, "slot_id": slot_id, "work_notes": work_notes,
                             "case_type": case_type, "case_note": case_note, "priority": priority,
                             "service_type": service_type or "Roof Inspection", "customer_name": customer_name,
                             "address": address, "city": city, "access_notes": access_notes}
        self.last_pending_id = cid
        return {"confirmation_id": cid, "instruction": "Now read the details to the caller and ask for a yes."}

    def _require(self, cid, kind):
        if cid not in self.confirmed:
            self.log("write_blocked", tool=kind, confirmation_id=cid, reason="not_confirmed")
            return None
        d = self.pending.get(cid)
        if not d or d["kind"] != kind:
            return None
        return d

    # ---- tools (write; gated) ------------------------------------------
    def create_inspection_booking(self, confirmation_id: str):
        """Create the service request and the inspection job for the details the caller confirmed."""
        d = self._require(confirmation_id, "booking")
        if d is None:
            return {"error": "NOT_CONFIRMED", "hint": "Nothing was saved. Call read_back NOW, before you say anything, then read it to the "
                                "caller once and wait for their yes."}
        key = f"{self.call_id}-{confirmation_id}"
        if any(j.get("idempotency_key") == key for j in self.db["jobs"].values()):
            return {"error": "DUPLICATE_IGNORED"}
        slot = next(s for s in self.db["slots"] if s["slot_id"] == d["slot_id"])
        if not slot["available"]:
            return {"error": "SLOT_TAKEN"}
        slot["available"] = False
        n = 5530 + self.id_base + len(self.db["jobs"])
        job_id, enq_id = f"B-{n}", f"R-{880 + self.id_base + len(self.db['enquiries'])}"
        new_customer = None
        if self.property_id is None:  # unknown caller: create customer and property from what was confirmed
            k = len(self.db["customers"])
            cust_id, prop_id = f"C-{2200 + k}", f"P-{90 + k}"
            self.db["customers"][cust_id] = {"name": d["customer_name"], "phone": self.caller_phone,
                                             "properties": [prop_id], "last_contact": None,
                                             "notes": [d["access_notes"]] if d["access_notes"] else [],
                                             "created_by": "Voice agent"}
            self.db["properties"][prop_id] = {"customer": cust_id, "address": d["address"], "city": d["city"],
                                              "access_notes": d["access_notes"]}
            self.customer_id, self.property_id, new_customer = cust_id, prop_id, cust_id
        prop = self.db["properties"][self.property_id]
        self.db["enquiries"][enq_id] = {"customer": self.customer_id, "property": self.property_id,
                                        "title": normalize_dates(d["work_notes"]), "source": "Voice agent",
                                        "priority": d["priority"], "status": "New Request"}
        self.db["jobs"][job_id] = {"enquiry": enq_id, "customer": self.customer_id, "property": self.property_id,
                                   "category": d["service_type"], "priority": d["priority"].title(),
                                   "start": f"{slot['date']} {slot['time']}", "tech": slot["tech"],
                                   "service_address": f"{prop['address']}, {prop['city']}",
                                   "notes": normalize_dates(d["work_notes"]),
                                   "access_notes": normalize_dates(prop.get("access_notes", "")),
                                   "status": "Schedule Confirmed", "idempotency_key": key}
        out = {"job_id": job_id, "enquiry_id": enq_id, "start": f"{slot['date']} {slot['time']}",
               "next_step": "Before you say anything, call read_back with kind sms. Then say the inspection is set and "
                            "ask whether you may text the details to the number they are calling from. Then wait."}
        if new_customer:
            out.update({"new_customer_id": new_customer, "new_property_id": self.property_id})
        return out

    def send_sms(self, confirmation_id: str, job_id: str):
        """Text the booking details to the caller's number, after the caller agreed to texts."""
        d = self._require(confirmation_id, "sms")
        if d is None:
            return {"error": "NOT_CONFIRMED",
                    "hint": "NOTHING WAS SENT. Do not tell the caller a text was sent. Ask whether you may text the "
                            "details, then wait for their reply before calling send_sms."}
        sid = f"M-{len(self.db['sms']) + 1}"
        job = self.db["jobs"].get(job_id, {})
        when = job.get("start", "")
        day = written_datetime(*when.split(" ")) if when else ""
        self.db["sms"][sid] = {"to": self.caller_phone, "job": job_id,
                               "text": f"Ridgeline Roofing: your {job.get('category', 'visit')} is booked for {day} "
                                       f"at {job.get('service_address', '')}. Reply C to cancel."}
        return {"sms_id": sid, "sent": True}

    def create_case(self, confirmation_id: str):
        """Create a separate case (for example a crew complaint) from the details the caller confirmed."""
        d = self._require(confirmation_id, "case")
        if d is None:
            return {"error": "NOT_CONFIRMED", "hint": "Call read_back, read it to the caller and wait for yes."}
        cid = f"K-{902 + self.id_base + len(self.db['cases'])}"
        self.db["cases"][cid] = {"customer": self.customer_id, "type": d["case_type"], "priority": d["priority"],
                                 "note": normalize_dates(d["case_note"]), "callback": CONTRACTOR["callback_promise"],
                                 "status": "Open"}
        return {"case_id": cid, "callback": CONTRACTOR["callback_promise"]}

    def transfer_to_human(self, reason: str):
        """Transfer the call to the office team (or create an urgent callback if closed)."""
        self.transferred = True
        cid = f"K-{902 + self.id_base + len(self.db['cases'])}"
        quotes = "; ".join(f"{k}: \"{v}\"" for k, v in self.triage_words.items() if v)
        self.db["cases"][cid] = {"customer": self.customer_id, "type": "emergency_transfer", "priority": "urgent",
                                 "note": normalize_dates(f"Urgent: caller sent to the office team live. Reason: {reason}. "
                                                         f"Caller's own words: {quotes or 'not recorded'}."),
                                 "callback": "immediate", "status": "Transferred to office"}
        return {"transferred": True, "reason": reason, "case_id": cid}

    def save_partial_lead(self, reason: str):
        """Called by the system, not the model, when a call ends before a booking or a normal goodbye. Saves what the
        caller said as an UNCONFIRMED lead plus a callback task, and writes the call log, so no call leaves nothing."""
        if self.call_id in self.db["calls"]:
            return None
        said = " ".join(self.caller_turns).strip()
        note = normalize_dates(said[:240]) if said else "The caller did not say anything."
        enq = f"R-{880 + self.id_base + len(self.db['enquiries'])}"
        self.db["enquiries"][enq] = {"customer": self.customer_id, "property": self.property_id,
                                     "title": f"Unfinished call (not confirmed): {note}", "source": "Voice agent",
                                     "priority": "normal", "status": "Incomplete lead", "phone": self.caller_phone}
        cid = f"K-{902 + self.id_base + len(self.db['cases'])}"
        self.db["cases"][cid] = {"customer": self.customer_id, "type": "callback", "priority": "normal",
                                 "note": f"Call back {self.caller_phone}. The call ended ({reason}) before a booking. "
                                         "Details are unconfirmed.", "callback": CONTRACTOR["callback_promise"],
                                 "status": "Open"}
        self.finalize_call("partial_lead" if said else "no_answer",
                           f"Call ended early ({reason}). Saved an unconfirmed lead {enq} and callback task {cid}.")
        return {"lead": enq, "case": cid}

    def finalize_call(self, outcome: str, summary: str):
        """Write the call log. Always run at the end of every call, even if the caller hung up."""
        self.db["calls"][self.call_id] = {"customer": self.customer_id, "phone": self.caller_phone,
                                          "outcome": outcome, "summary": normalize_dates(summary),
                                          "records": {"jobs": list(self.db["jobs"]),
                                                      "cases": list(self.db["cases"])}}
        if self.customer_id:
            self.db["customers"][self.customer_id]["last_contact"] = f"call {self.call_id}"
        return {"call_id": self.call_id, "logged": True}


TOOL_SPECS = [
    {"name": "lookup_customer", "description": Session.lookup_customer.__doc__,
     "params": {"phone": ("string", "Caller phone number from caller ID, e.g. +15550142")}},
    {"name": "match_property", "description": Session.match_property.__doc__,
     "params": {"address_spoken": ("string", "The street address exactly as the caller said it")}},
    {"name": "check_service_area", "description": Session.check_service_area.__doc__,
     "params": {"city": ("string", "The city the caller gave, e.g. Everett")}},
    {"name": "get_availability", "description": Session.get_availability.__doc__,
     "params": {"date_from": ("string", "YYYY-MM-DD"), "date_to": ("string", "YYYY-MM-DD")}},
    {"name": "record_triage", "description": Session.record_triage.__doc__,
     "params": {"water_fast": ("boolean", "Water coming in fast or flooding"),
                "near_electrical": ("boolean", "Water near lights, outlets or the electrical panel"),
                "ceiling_sagging": ("boolean", "Ceiling sagging or part of the roof collapsed"),
                "water_fast_words": ("string", "The caller's own words answering question (a), copied exactly"),
                "electrical_words": ("string", "The caller's own words answering question (b), copied exactly"),
                "ceiling_words": ("string", "The caller's own words answering question (c), copied exactly"),
                "other_danger": ("boolean", "Caller mentioned fire, smoke, sparks or collapse")}},
    {"name": "read_back", "description": Session.read_back.__doc__,
     "params": {"kind": ("string", "booking, case or sms"), "summary": ("string", "Plain-words summary you will read"),
                "slot_id": ("string", "For booking: the slot_id chosen"),
                "work_notes": ("string", "For booking: the work description, with roofing terms spelled correctly"),
                "case_type": ("string", "For case: e.g. crew_complaint"),
                "case_note": ("string", "For case: the note to record"),
                "priority": ("string", "normal, urgent or high"),
                "service_type": ("string", "Roof Inspection, Repair Service or Install/Replace"),
                "customer_name": ("string", "New customer only: full name as the caller spelled it"),
                "address": ("string", "New customer only: street address"),
                "city": ("string", "New customer only: city"),
                "access_notes": ("string", "New customer only: gate code, pets or other access notes")}},
    {"name": "create_inspection_booking", "description": Session.create_inspection_booking.__doc__,
     "params": {"confirmation_id": ("string", "The id returned by read_back")}},
    {"name": "send_sms", "description": Session.send_sms.__doc__,
     "params": {"confirmation_id": ("string", "The id returned by read_back with kind sms"),
                "job_id": ("string", "The job id returned by create_inspection_booking")}},
    {"name": "create_case", "description": Session.create_case.__doc__,
     "params": {"confirmation_id": ("string", "The id returned by read_back")}},
    {"name": "transfer_to_human", "description": Session.transfer_to_human.__doc__,
     "params": {"reason": ("string", "Why the call is being transferred")}},
    {"name": "finalize_call", "description": Session.finalize_call.__doc__,
     "params": {"outcome": ("string", "booked, case_only, transferred, abandoned or info_only"),
                "summary": ("string", "Two-sentence summary of the call")}},
]
