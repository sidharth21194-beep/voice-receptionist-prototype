# Voice Receptionist for Home-Service Contractors (prototype)

A working AI phone receptionist for a roofing contractor, plus a self-serve setup flow for the contractor.
It answers a call, asks fixed safety questions, books an inspection, and only saves what the caller has heard and agreed to.

All businesses, callers and records are fictional. This is a portfolio prototype, not a product.

Live demo: https://voice-receptionist-demo-swart.vercel.app (the call page and the setup flow at /setup.html). Calling the agent needs a passcode; ask me for one.

## What is in here

| Part | Folder | What it is |
|---|---|---|
| Voice agent | `agent/` | The live agent (LiveKit + Deepgram + Claude Haiku) and a text-only version used for repeatable tests |
| Mock records | `agent/mock_records.py` | A stand-in field-service system: customers, properties, schedule, bookings, texts, cases, call logs |
| Live call page | `live/index.html` | Call the agent from a browser and watch each step and record change live |
| Contractor setup | `live/setup.html` | Eight-step self-serve onboarding to a successful test call, a dashboard, and versions of the agent |
| Token service | `live/api/token.js`, `live/token_server.py` | Issues short-lived call tokens, checks an optional passcode, rate-limits calls |
| Evaluation | `scripts/eval_runs.py` | Runs simulated callers through scenarios repeatedly and scores the saved records |

## How a call works

```
Caller's voice
  -> LiveKit room (audio transport; a phone line in production, a browser microphone in the demo)
  -> Silero voice detection + LiveKit turn model (has the caller finished?)
  -> Deepgram Nova-3 (speech to text, with a roofing word list)
  -> Claude Haiku 5.5 (decides, calls tools on the records)
  -> Deepgram Aura-2 (text to speech, streamed)
  -> LiveKit room -> caller
```

The agent is a Python program that runs the loop above for each call. The model suggests the next step; the program decides what is allowed.

## Design decisions worth reading

- **Confirm before write.** A read-back step stores exactly what the caller will hear and returns a confirmation id. The write tools accept only that id, after a clear yes. The saved record cannot differ from what was heard, even if the model misbehaves.
- **Safety in code, not in the prompt.** Three fixed safety questions cannot be skipped, the caller's own words must back each answer, and any yes transfers to a human with an urgent case and no booking.
- **A cascade, not speech-to-speech.** A text step lets the system read back and validate a booking before saving. Speech-to-speech can be faster but has no such step.
- **No call ends with nothing logged.** Silence ("Are you still there?" after 4 s, twice, then a goodbye with a 3 s grace), a hang-up or a time limit saves an unconfirmed lead, a callback task and a call log.
- **One retry key** means a retried request never books twice. An interruption discards any pending confirmation.
- **Contractor settings cannot weaken safety.** Free-text rules are added under a heading that says they never override the safety or confirmation rules, and those rules also live in code.

## Results from this prototype

Measured on the prototype, with simulated callers in text and one live voice test. These show consistency, not accuracy on real phone calls.

- First word after the caller stops: median 1.22 s, slowest 2.7 s (13 replies on the cloud-hosted agent; replies after a records look-up were slowest).
- Scenario runs: fallback time 6/6, trade word correction 6/6, interruption 6/6, emergency leak 3/3, outside the service area 3/3, a second need captured 5/6.
- Silence and unfinished lead: passed once, by voice, on the cloud agent.

## What is not built

- A real phone line (SIP). The demo uses a browser microphone, so narrowband phone audio, noise and carrier delay are untested.
- Callback after poor audio, remembering a caller across a dropped call, technician availability and auto-assign.
- Production cost per call and concurrency were not measured. Each layer has one vendor today.

## Run it

You need accounts and keys for Anthropic, Deepgram and LiveKit. Copy `.env.example` to `.env` and fill it in. Never commit `.env`.

```powershell
pip install -r requirements.txt

# repeatable text-only tests of the agent logic (uses the Anthropic key)
python scripts/eval_runs.py emergency_sim 3

# live agent against LiveKit (needs the LiveKit and Deepgram keys)
python agent/live_agent.py dev

# local token service and pages
python live/token_server.py          # port 8787
cd live; python -m http.server 8766  # open http://localhost:8766/ and setup.html
```

To deploy: `python scripts/make_deploy.py` builds a container folder for `lk agent deploy`; the `live/` folder deploys to Vercel with `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` and an optional `DEMO_PASSCODE` as environment variables. Set `DEMO_DISABLED=1` to switch the live demo off.

## Stack

LiveKit Agents and LiveKit Cloud, Silero VAD, LiveKit turn detector, Deepgram Nova-3 and Aura-2, Claude Haiku 5.5, Python, plain HTML and JavaScript pages, Vercel.
