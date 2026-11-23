"""End-to-end test of the live agent without a human: a simulated caller joins a real LiveKit room.

The caller's words come from a Claude-played Tony Marsh (same brief as the recorded call), are turned into
speech with Deepgram, and are streamed into the room as microphone audio. The agent's data-channel trace and
audio are captured, so we can check the pipeline and measure first-word time from the caller's side.

Run: python live/smoke_test.py [max_turns]
"""
import asyncio
import json
import os
import statistics as st
import sys
import time
import urllib.request

from dotenv import load_dotenv
from livekit import rtc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agent"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
load_dotenv(os.path.join(ROOT, ".env"))
import anthropic  # noqa: E402
from scenarios import TONY_BRIEF  # noqa: E402

DG = os.environ["DEEPGRAM_API_KEY"]
RATE = 24000
FRAME = RATE // 100  # 10 ms


def tts_pcm(text, voice="aura-2-apollo-en"):
    req = urllib.request.Request(
        f"https://api.deepgram.com/v1/speak?model={voice}&encoding=linear16&container=none&sample_rate={RATE}",
        data=json.dumps({"text": text}).encode(),
        headers={"Authorization": "Token " + DG, "Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=60).read()


async def main(max_turns=14):
    from audio_warmup import warm_resamplers
    warm_resamplers()
    token_resp = json.loads(urllib.request.urlopen(urllib.request.Request(
        "http://localhost:8787/token", data=json.dumps({"mode": "new"}).encode(),
        headers={"content-type": "application/json"})).read())
    room = rtc.Room()
    msgs, agent_rms_log = [], []
    state = {"agent_audio_at": None, "last_agent_loud": 0.0, "agent_transcripts": [], "done": False,
             "agent_state": "", "state_at": 0.0}

    @room.on("data_received")
    def _data(pkt: rtc.DataPacket):
        if pkt.topic == "voice-trace":
            m = json.loads(pkt.data.decode())
            msgs.append((time.time(), m))
            if m["t"] == "transcript" and m["speaker"] == "agent":
                state["agent_transcripts"].append(m["text"])
            if m["t"] == "state":
                state["agent_state"], state["state_at"] = m["state"], time.time()

    async def read_agent_audio(track):
        async for ev in rtc.AudioStream(track):
            import numpy as np
            a = np.frombuffer(ev.frame.data, dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt((a ** 2).mean())) if len(a) else 0.0
            if rms > 600:
                now = time.time()
                if state["agent_audio_at"] is None:
                    state["agent_audio_at"] = now
                state["last_agent_loud"] = now

    @room.on("track_subscribed")
    def _sub(track, pub, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            asyncio.ensure_future(read_agent_audio(track))

    await room.connect(token_resp["url"], token_resp["token"])
    source = rtc.AudioSource(RATE, 1)
    track = rtc.LocalAudioTrack.create_audio_track("mic", source)
    await room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))

    silence = b"\x00\x00" * FRAME

    async def push(pcm_bytes):
        for i in range(0, len(pcm_bytes) - FRAME * 2 + 1, FRAME * 2):
            await source.capture_frame(rtc.AudioFrame(pcm_bytes[i:i + FRAME * 2], RATE, 1, FRAME))
            await asyncio.sleep(0.0095)

    async def silence_until(cond, timeout):
        t0 = time.time()
        while time.time() - t0 < timeout and not cond():
            await source.capture_frame(rtc.AudioFrame(silence, RATE, 1, FRAME))
            await asyncio.sleep(0.0095)

    client = anthropic.Anthropic()
    transcript, client_first_word = [], []

    async def wait_agent_done(min_wait=1.5):
        """Wait for the agent to start speaking, then for it to report 'listening' for a moment."""
        await silence_until(lambda: state["agent_audio_at"] is not None, 14)
        t0 = time.time()
        while time.time() - t0 < 40:
            await silence_until(lambda: False, 0.2)
            if state["agent_state"] == "listening" and time.time() - state["state_at"] > 1.0:
                break

    # greeting
    await wait_agent_done()
    transcript.append(("Ava", state["agent_transcripts"][-1] if state["agent_transcripts"] else ""))
    line = ("Hi, I need my roof fixed. A storm last week knocked some ridge shingles loose, and I think the flashing "
            "around the vent is lifting. Could someone come out next Tuesday afternoon, or Wednesday morning?")
    for turn in range(max_turns):
        print(f"[{turn + 1}] CALLER: {line}")
        transcript.append(("Tony", line))
        state["agent_audio_at"] = None
        n_before = len(state["agent_transcripts"])
        synth = asyncio.create_task(asyncio.to_thread(tts_pcm, line))  # keep the mic stream alive meanwhile
        await silence_until(synth.done, 30)
        await push(synth.result())
        t_last = time.time()
        await silence_until(lambda: state["agent_audio_at"] is not None, 14)
        if state["agent_audio_at"]:
            client_first_word.append(int((state["agent_audio_at"] - t_last) * 1000))
        await wait_agent_done()
        await asyncio.sleep(0.4)
        reply = state["agent_transcripts"][-1] if len(state["agent_transcripts"]) > n_before else "(no reply)"
        print(f"    AVA: {reply}   [first word, caller side: {client_first_word[-1] if client_first_word else '?'} ms]")
        transcript.append(("Ava", reply))
        if any(m["t"] == "end" for _, m in msgs) or "goodbye" in reply.lower() or "good day" in reply.lower() \
                or "great day" in reply.lower() or "see you" in reply.lower():
            break
        convo = "\n".join(f"{s}: {t}" for s, t in transcript)
        r = client.messages.create(model="claude-haiku-5-5", max_tokens=120, thinking={"type": "disabled"},
                                   system=TONY_BRIEF, messages=[{"role": "user",
                                                                 "content": f"Call so far:\n{convo}\n\nWrite Tony's next line only."}])
        line = "".join(b.text for b in r.content if b.type == "text").strip().strip('"')
        if os.environ.get("CONFIRM_PHRASE") and "is that right" in reply.lower():
            line = os.environ["CONFIRM_PHRASE"]  # force an unusual way of saying yes to the booking read-back
        if line.startswith("[HANGUP]"):
            break
    await asyncio.sleep(2)
    await room.disconnect()

    steps = [m["step"] for _, m in msgs if m["t"] == "step"]
    mets = [m for _, m in msgs if m["t"] == "metrics"]
    recs = [m for _, m in msgs if m["t"] == "records"]
    print("\n=== SUMMARY ===")
    print("trace steps received:", len(steps), "| kinds:", sorted({s['kind'] for s in steps}))
    print("tools:", [s["tool"]["name"] for s in steps if s.get("tool")])
    print("safety-net steps:", [s["detail"][:70] for s in steps if s["kind"] == "safety"])
    print("agent-measured first word ms:", [m["first_word_ms"] for m in mets])
    if mets:
        print("  average", int(st.mean(m["first_word_ms"] for m in mets)))
    print("caller-side first word ms:", client_first_word)
    if recs:
        print("records:", [(c["type"], c["action"]) for c in recs[-1]["changes"]])


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 14))
