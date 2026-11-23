"""Scripted caller lines. asr_note simulates the word-level confidence a real ASR returns."""

GREETING = ("Thanks for calling Ridgeline Roofing, this is Ava, the virtual assistant. "
            "This call may be recorded to help with your request. How can I help?")

TONY_BRIEF = """You are Tony Marsh (a fictional customer for a demo), a homeowner phoning Ridgeline Roofing from your mobile on a calm, dry afternoon. You are confident, brisk and a little witty, but polite. You speak in short, natural sentences, one thing at a time, like a real caller. Reply with only what Tony says out loud: no stage directions, no quotes.
Facts and behaviour:
- Safety questions: there is no leak and no water inside at all, nothing near lights, outlets or the panel, ceiling fine. Answer "no" briefly and do not invent any other problem or request.
- You are a new customer. A storm last week knocked some ridge shingles loose and you think the flashing around a roof vent is lifting. You want someone to come and fix it (a repair), not a full replacement.
- Your name is Tony Marsh. If asked to spell the last name say: "S, T, A, R, K." Your callback number is the one you are calling from.
- Your address is 1 Marsh Lane, Everett. Say it as "One Marsh Lane, in Everett."
- You can do next Tuesday afternoon; if that is not available, Wednesday morning is fine.
- Access: there is a dog in the backyard, friendly but loud, so the crew should use the front. No gate code.
- Say yes to read-backs that are right. If something is wrong, correct it briefly.
- Agree to a text message with the details.
- Keep every reply to one short sentence (under 25 words). Never ask the agent questions and never add requests that are not listed here; the dog is already covered by the access note.
- When asked if there is anything else, say no. After the agent says goodbye, reply exactly [HANGUP]."""

MARIA_BRIEF = """You are Maria Lopez, a homeowner phoning Ridgeline Roofing from your mobile on a rainy, windy afternoon. You are a little stressed but polite. You speak in short, natural sentences, one thing at a time, like a real caller. Reply with only what Maria says out loud: no stage directions, no quotes.
Facts and behaviour:
- Safety questions: it is only a drip in the hallway and you put a bucket under it. No stream of water, nothing near lights, outlets or the electrical panel, ceiling not sagging.
- Your address is 118 Maple Grove Lane. Say it as "One eighteen Maple Grove Lane".
- If the agent offers Friday morning times, say "Ten thirty." Then, when the agent reads that back, you realise you mixed it up: you meant 9 AM. Say "Sorry, nine, not ten thirty." After that you want Friday at 9 AM and you stay with 9 AM: never go back to 10:30.
- Accept either way of saying the house number ("one eighteen" or "one one eight"); do not correct the agent's pronunciation.
- If the agent asks whether you meant "valley metal", say: "Valley metal. The metal where the two roof slopes meet."
- Say yes to read-backs that are right. If something is wrong, correct it briefly.
- Agree to a text message with the details.
- When asked if there is anything else after the booking, say your crew left nails in your driveway yesterday and you are worried about a flat tire. Agree to the office calling you back.
- When everything is done, say "No, that's all. Thanks." After the agent says goodbye, reply exactly [HANGUP]."""


DAN_BRIEF = """You are Dan Parker (a fictional customer), a homeowner phoning Ridgeline Roofing from your mobile during a storm. You are worried and a bit rushed. You speak in short, natural sentences, like a real caller. Reply with only what Dan says out loud: no stage directions, no quotes.
Facts and behaviour:
- Water is dripping through the kitchen ceiling right next to a light fixture, and the ceiling is starting to sag.
- If asked whether water is coming in fast like a stream or flooding: say "No, it is a steady drip."
- If asked whether water is near light fixtures, outlets or the electrical panel: say "Yes, it is dripping right next to the light fixture."
- If asked whether the ceiling is sagging or part of the roof has collapsed: say "Yes, the ceiling is sagging."
- If the agent says it is connecting you to the team, reply exactly [HANGUP].
- Keep every reply to one short sentence."""

LENA_BRIEF = """You are Lena Wu (a fictional customer), a homeowner phoning Ridgeline Roofing from your mobile on a calm afternoon. You are polite and practical. You speak in short, natural sentences, one thing at a time. Reply with only what Lena says out loud: no stage directions, no quotes.
Facts and behaviour:
- You want a roof inspection because a few shingles look worn. No leak, no water inside, nothing near lights or outlets, ceiling fine: answer "no" briefly to any safety question.
- You are a new customer. Your name is Lena Wu; if asked to spell the last name say "W, U." Your callback number is the one you are calling from.
- Your address is 412 Pacific Avenue in Tacoma. Say it as "Four twelve Pacific Avenue, in Tacoma."
- If the agent says you are outside its service area and offers a callback from the office, say yes please, a callback is fine.
- Say yes to read-backs that are right. When asked if there is anything else, say no. After the agent says goodbye, reply exactly [HANGUP].
- Keep every reply to one short sentence."""

SCENARIOS = {
    "emergency_sim": {
        "caller_phone": "+15550188",
        "caller_voice": "aura-2-apollo-en",
        "caller_name": "Dan Parker",
        "call_id": "L-31009", "id_base": 2,
        "greeting": GREETING,
        "caller_brief": DAN_BRIEF,
        "first_line": {"text": "Hi, there is water coming through my kitchen ceiling, and it is dripping right by the light fixture."},
    },
    "outside_sim": {
        "caller_phone": "+15550199",
        "caller_voice": "aura-2-luna-en",
        "caller_name": "Lena Wu",
        "call_id": "L-31010", "id_base": 3,
        "greeting": GREETING,
        "caller_brief": LENA_BRIEF,
        "first_line": {"text": "Hi, I'd like a roof inspection. A few of my shingles look worn."},
    },
    "tony_sim": {
        "caller_phone": "+15550177",
        "caller_voice": "aura-2-apollo-en",
        "caller_name": "Tony Marsh",
        "call_id": "L-31008", "id_base": 1,
        "greeting": GREETING,
        "caller_brief": TONY_BRIEF,
        "first_line": {"text": "Hi, I need my roof fixed. A storm last week knocked some ridge shingles loose, and I "
                               "think the flashing around the vent is lifting. Could someone come out next Tuesday "
                               "afternoon, or Wednesday morning?"},
    },
    "maria_sim": {
        "caller_phone": "+15550142",
        "caller_voice": "aura-2-luna-en",
        "caller_name": "Maria Lopez",
        "greeting": GREETING,
        "caller_brief": MARIA_BRIEF,
        "first_line": {"text": "Hi, I've got a leak near my chimney. The hail damaged my architectural shingles and "
                               "fascia board, and can someone check the valley matter too? Thursday around 2 PM "
                               "would be great, or Friday morning.",
                       "asr_note": "low confidence on 'valley matter' (0.41); likely alternative: 'valley metal'",
                       "asr_flag": ("valley matter", "valley metal")},
        "interrupt": {"agent_contains": "10:30 AM", "cut_after": "10:30 AM", "caller_says": "Sorry, nine, not ten thirty."},
    },
    "maria_main": {
        "caller_phone": "+15550142",
        "greeting": GREETING,
        "caller_lines": [
            {"text": "Hi, I've got a leak near my chimney. The hail damaged my architectural shingles and fascia "
                     "board, and can someone check the valley matter too? Thursday around 2 PM would be great, "
                     "or Friday morning.",
             "asr_note": "low confidence on 'valley matter' (0.41); likely alternative: 'valley metal'"},
            {"text": "No, just a drip in the hallway. I've put a bucket under it."},
            {"text": "No, none of that."},
            {"text": "One eighteen Maple Grove Lane."},
            {"text": "Ten thirty."},
            {"text": "Sorry, nine, not ten thirty.", "barge_in_after": "10:30 AM"},
            {"text": "Yes."},
            {"text": "Valley metal. The metal where the two roof slopes meet."},
            {"text": "Yes, please."},
            {"text": "Yes."},
            {"text": "Yes, your crew left nails in my driveway yesterday. I'm worried about a flat tire."},
            {"text": "Yes."},
            {"text": "No, that's all. Thanks."},
        ],
    },
}
