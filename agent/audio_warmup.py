"""Initialise LiveKit's native audio resampler once, on one thread, before any call starts.

On Windows the resampler (soxr) can hit an assertion in its shared FFT cache ("LSX_FFT_BR == NULL") when two
resamplers are first created at the same moment, which is exactly what happens when a call opens its speech
recognition input and speech output together. That assertion shows a pop-up and kills the process. Creating one
resampler of each kind up front fills the cache single-threaded, so later creations skip the racy first step.
"""
from livekit import rtc

RATES = [(48000, 16000), (24000, 48000), (48000, 24000), (16000, 48000), (24000, 16000), (16000, 24000),
         (44100, 48000), (48000, 44100), (24000, 24000)]


def warm_resamplers():
    for quality in rtc.AudioResamplerQuality:
        for a, b in RATES:
            try:
                r = rtc.AudioResampler(a, b, num_channels=1, quality=quality)
                r.push(bytearray((a // 50) * 2))
                r.flush()
            except Exception:
                pass
