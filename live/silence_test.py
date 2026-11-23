"""A caller who joins and says nothing: checks the 'are you still there' follow-ups and the polite hang-up."""
import asyncio, json, os, sys, time, urllib.request
from dotenv import load_dotenv
from livekit import rtc
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agent"))
load_dotenv(os.path.join(ROOT, ".env"))
from audio_warmup import warm_resamplers

async def main():
    warm_resamplers()
    tok = json.loads(urllib.request.urlopen(urllib.request.Request("http://localhost:8787/token", data=b'{"mode":"new"}',
                     headers={"content-type": "application/json"})).read())
    room = rtc.Room(); t0 = time.time(); log = []
    @room.on("data_received")
    def _d(p):
        if p.topic != "voice-trace": return
        m = json.loads(p.data.decode())
        if m["t"] == "transcript" and m["speaker"] == "agent": log.append((round(time.time() - t0, 1), m["text"]))
        if m["t"] == "state" and m["state"] in ("speaking", "listening"): log.append((round(time.time() - t0, 1), "[" + m["state"] + "]"))
        if m["t"] == "end": log.append((round(time.time() - t0, 1), "END " + m["reason"]))
        if m["t"] == "records": log.append((round(time.time() - t0, 1), "RECORDS " + "; ".join(f"{c['type']} {c['id']} {c['action']}" for c in m["changes"])))
        if m["t"] == "step" and m["step"]["kind"] == "tool_write": log.append((round(time.time() - t0, 1), "STEP " + m["step"]["title"]))
    await room.connect(tok["url"], tok["token"])
    src = rtc.AudioSource(24000, 1); tr = rtc.LocalAudioTrack.create_audio_track("mic", src)
    await room.local_participant.publish_track(tr, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    sil = b"\x00\x00" * 240
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    grace = mode in ("grace", "during")
    trigger = "[speaking]" if mode == "during" else "[listening]"
    said, pcm = False, None
    if grace:  # speak a short line one second after the goodbye has finished playing
        req = urllib.request.Request(
            "https://api.deepgram.com/v1/speak?model=aura-2-apollo-en&encoding=linear16&container=none&sample_rate=24000",
            data=json.dumps({"text": "Wait, wait. I'm still here."}).encode(),
            headers={"Authorization": "Token " + os.environ["DEEPGRAM_API_KEY"], "Content-Type": "application/json"})
        pcm = urllib.request.urlopen(req).read()
    while time.time() - t0 < 70:
        if grace and not said and any("Goodbye" in str(x[1]) for x in log) and log[-1][1] == trigger:
            said = True
            for _ in range(150 if mode == 'during' else 100):
                await src.capture_frame(rtc.AudioFrame(sil, 24000, 1, 240)); await asyncio.sleep(0.0095)
            log.append((round(time.time() - t0, 1), "<<caller speaks during the grace window>>"))
            for i in range(0, len(pcm) - 479, 480):
                await src.capture_frame(rtc.AudioFrame(pcm[i:i + 480], 24000, 1, 240)); await asyncio.sleep(0.0095)
        await src.capture_frame(rtc.AudioFrame(sil, 24000, 1, 240)); await asyncio.sleep(0.0095)
    await room.disconnect()
    for r in log: print(r)
asyncio.run(main())
