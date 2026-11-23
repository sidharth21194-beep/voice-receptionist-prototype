"""Join a call through the deployed token function with custom contractor settings; print what the agent says first."""
import asyncio, json, os, sys, time, urllib.request
from livekit import rtc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"))
from audio_warmup import warm_resamplers

async def main():
    warm_resamplers()
    body = {"mode": "new", "passcode": sys.argv[1], "persona": "Riley", "business": "Blue Peak Roofing", "hours": "Mon-Sat 7 AM to 6 PM",
            "voice": "aura-2-apollo-en", "greeting": "Blue Peak Roofing, Riley speaking. This call may be recorded to help with your request. What can I do for you?",
            "rules": "Always ask whether the home is a single-storey house.", "service_area": "Pierce County, WA", "services": ["Roof Inspection"],
            "keyterms": ["Malarkey shingles"]}
    req = urllib.request.Request("https://voice-receptionist-demo.vercel.app/api/token", data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    tok = json.loads(urllib.request.urlopen(req).read())
    room = rtc.Room(); got = []; t0 = time.time()
    @room.on("data_received")
    def _d(p):
        if p.topic == "voice-trace":
            m = json.loads(p.data.decode())
            if m["t"] in ("hello", "transcript"): got.append((round(time.time() - t0, 1), m))
    await room.connect(tok["url"], tok["token"])
    src = rtc.AudioSource(24000, 1); tr = rtc.LocalAudioTrack.create_audio_track("mic", src)
    await room.local_participant.publish_track(tr, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    sil = b"\x00\x00" * 240
    while time.time() - t0 < 14:
        await src.capture_frame(rtc.AudioFrame(sil, 24000, 1, 240)); await asyncio.sleep(0.0095)
    await room.disconnect()
    for t, m in got: print(t, m.get("persona") or m.get("text"), "|", m.get("business", ""))
asyncio.run(main())
