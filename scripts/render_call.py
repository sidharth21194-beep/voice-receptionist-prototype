"""Render a trace into a two-voice call recording plus a timeline for the presentation page.

Usage: python scripts/render_call.py traces/maria_representative.json maria_call
Needs DEEPGRAM_API_KEY in .env (Aura-2 voices) and ffmpeg on PATH.
Timing is composed, not live: gaps between speakers are set by rule, and the interruption is built by
overlapping the caller's audio onto the agent's audio at the logged barge-in point.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "recordings", "raw", "tts_cache")
OUT = os.path.join(ROOT, "recordings", "final")
VOICES = {"agent": "aura-2-thalia-en", "caller": "aura-2-luna-en"}
AGENT_GAP, CALLER_GAP, OVERLAP = 0.85, 0.55, 0.55

for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
    if line.startswith("DEEPGRAM_API_KEY="):
        KEY = line.split("=", 1)[1].strip()


LETTER_NAMES = {"A": "Ay", "B": "Bee", "C": "See", "D": "Dee", "E": "Ee", "F": "Eff", "G": "Gee", "H": "Aitch",
                "I": "Eye", "J": "Jay", "K": "Kay", "L": "El", "M": "Em", "N": "En", "O": "Oh", "P": "Pee",
                "Q": "Kyoo", "R": "Are", "S": "Ess", "T": "Tee", "U": "You", "V": "Vee", "W": "Double you",
                "X": "Ex", "Y": "Why", "Z": "Zee"}


def spell_out(m):
    # "S. T. A. R. K." is read letter by letter by Aura-2; "S, T, A, R, K" drops the first letter and
    # phonetic names ("Ess, Tee, Ay") confuse recognisers. Verified with Nova-3 on the rendered audio.
    letters = re.findall(r"[A-Z]", m.group(0))
    return ". ".join(letters) + "."


def speakable(text):
    # spelled-out names ("S, T, A, R, K" or "S-T-A-R-K"): the voice swallows a leading bare "S", so spell phonetically
    text = re.sub(r"\b[A-Z](?:\s*[,\-]\s*[A-Z]\b){2,}[.,]?", spell_out, text)
    text = re.sub(r"\b(\d{2,4})(?= [A-Z])", lambda m: " ".join(m.group(1)), text)  # house numbers digit by digit
    text = text.replace(", WA", ", Washington").replace("10:30", "ten thirty")
    return text


def tts(text, voice):
    os.makedirs(CACHE, exist_ok=True)
    spoken = speakable(text)
    path = os.path.join(CACHE, hashlib.md5((voice + spoken).encode()).hexdigest() + ".wav")
    if not os.path.exists(path):
        req = urllib.request.Request(
            f"https://api.deepgram.com/v1/speak?model={voice}&encoding=linear16&container=wav&sample_rate=24000",
            data=json.dumps({"text": spoken}).encode(),
            headers={"Authorization": "Token " + KEY, "Content-Type": "application/json"})
        with open(path, "wb") as f:
            f.write(urllib.request.urlopen(req, timeout=60).read())
    # Deepgram streams the WAV with an unknown-length header, so the header's frame count is wrong:
    # derive the duration from the file size (16-bit mono, 24 kHz, 44-byte header).
    dur = (os.path.getsize(path) - 44) / (2 * 24000)
    return path, dur


def main(trace_path, name):
    d = json.load(open(os.path.join(ROOT, trace_path), encoding="utf-8"))
    turns = d["turns"]
    VOICES["caller"] = d.get("caller_voice") or VOICES["caller"]
    clips, timeline, t = [], [], 0.0
    prev_speaker = None
    for i, turn in enumerate(turns):
        spk = turn["speaker"]
        interrupted = "spoken_until_interrupt" in turn
        text = turn["spoken_until_interrupt"] if interrupted else turn["text"]
        path, dur = tts(text, VOICES[spk])
        speed = CALLER_SPEED if spk == "caller" else 1.0
        dur = dur / speed
        if prev_speaker is not None:
            gap = AGENT_GAP if spk == "agent" else CALLER_GAP
            nxt_interrupts = (spk == "caller" and i > 0 and "spoken_until_interrupt" in turns[i - 1])
            if nxt_interrupts:  # caller starts talking over the end of the agent
                t = t - OVERLAP
            else:
                t += gap
        seg = {"i": i, "speaker": spk, "start": round(t, 2), "text": turn["text"], "spoken": text,
               "interrupted": interrupted, "asr_note": turn.get("asr_note")}
        clip = {"path": path, "start": t, "fade_out": None, "speed": speed}
        if interrupted:
            # the agent keeps talking for a moment after the caller begins, then is cut
            clip["trim"] = dur - OVERLAP + 0.2
            clip["fade_out"] = 0.12
            seg["end"] = round(t + clip["trim"], 2)
            t += clip["trim"] + OVERLAP - 0.2  # leaves t at the nominal end so the caller offset works
            t = t  # nominal end of the untrimmed clip
        else:
            seg["end"] = round(t + dur, 2)
            t += dur
        clips.append(clip)
        timeline.append(seg)
        prev_speaker = spk
    total = t + 1.0

    # tool events mapped into the gap before each agent turn
    ev = d["events"]
    agent_idx = [s for s in timeline if s["speaker"] == "agent"]
    ai, buf, tools_by_turn = 0, [], {}
    for e in ev:
        if e["kind"] == "tool_call" and not e.get("background"):
            buf.append(e)
        elif e["kind"] == "agent_says" and not e.get("scripted"):
            ai += 1
            if ai < len(agent_idx) and buf:
                tools_by_turn[agent_idx[ai]["i"]] = buf
            buf = []
    for seg in timeline:
        calls = tools_by_turn.get(seg["i"], [])
        seg["tools"] = [{"name": c["name"], "args": c["args"], "result": c["result"]} for c in calls]

    os.makedirs(OUT, exist_ok=True)
    json.dump({"duration": round(total, 2), "voices": VOICES, "segments": timeline},
              open(os.path.join(OUT, f"{name}_timeline.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    def mix(outfile, phone):
        inputs, filters, labels = [], [], []
        for k, c in enumerate(clips):
            inputs += ["-i", c["path"]]
            f = f"[{k}:a]"
            if c.get("speed", 1.0) != 1.0:
                f += f"atempo={c['speed']},"
            if c.get("trim"):
                f += f"atrim=0:{c['trim']:.3f},afade=t=out:st={c['trim'] - c['fade_out']:.3f}:d={c['fade_out']},"
            ms = int(max(c["start"], 0) * 1000)
            filters.append(f"{f}adelay={ms}|{ms}[a{k}]")
            labels.append(f"[a{k}]")
        n = len(clips)
        graph = ";".join(filters) + ";" + "".join(labels) + f"amix=inputs={n}:normalize=0[voices]"
        last = "[voices]"
        if phone:
            inputs += ["-f", "lavfi", "-i", f"anoisesrc=d={total:.2f}:c=pink:a=0.5:r=24000"]
            graph += f";[{n}:a]lowpass=f=5000,highpass=f=300,volume=0.035[rain]"
            graph += ";[voices][rain]amix=inputs=2:normalize=0[mixed];[mixed]highpass=f=250,lowpass=f=4200[out]"
            last = "[out]"
        subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", last,
                        "-t", f"{total:.2f}", "-ar", "24000", "-ac", "1", "-b:a", "64k", outfile], check=True)

    mix(os.path.join(OUT, f"{name}_clean.mp3"), phone=False)
    mix(os.path.join(OUT, f"{name}_phone_rain.mp3"), phone=True)
    print("duration", round(total, 1), "s;", len(timeline), "segments;", OUT)


CALLER_SPEED = 1.0

if __name__ == "__main__":
    if len(sys.argv) > 3:
        CALLER_SPEED = float(sys.argv[3])  # e.g. 1.15 to speed up a slow caller voice (pitch preserved)
    main(sys.argv[1], sys.argv[2])
