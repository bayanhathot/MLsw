"""Generate Cuemix's original deterministic 60-second demo audio asset.

This uses only synthesized sine waves; it contains no sampled or third-party
recording. Run ``python app/static/audio/generate_demo.py`` to reproduce the
asset on the project's supported CPython/build and verify its documented hash.
"""

from math import exp, pi, sin
from pathlib import Path
import struct
import wave

SAMPLE_RATE = 22_050
DURATION_SECONDS = 60
OUTPUT = Path(__file__).with_name("cuemix-demo.wav")

# MIDI-note chord progression: Cmaj7, Am7, Fmaj7, G6.
CHORDS = (
    (48, 52, 55, 59),
    (45, 48, 52, 55),
    (41, 45, 48, 52),
    (43, 47, 50, 52),
)


def frequency(midi_note: int) -> float:
    return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))


def sample_at(index: int) -> int:
    time = index / SAMPLE_RATE
    chord = CHORDS[int(time // 8) % len(CHORDS)]
    pad = 0.0
    for voice, note in enumerate(chord):
        hz = frequency(note)
        phase_wobble = 0.012 * sin(2 * pi * (0.07 + voice * 0.01) * time)
        pad += 0.13 * sin(2 * pi * hz * time + phase_wobble)

    beat_phase = time % 1.0
    kick = 0.20 * exp(-9.0 * beat_phase) * sin(2 * pi * 58.0 * beat_phase)
    shimmer = 0.045 * sin(2 * pi * frequency(chord[-1] + 12) * time)
    fade = min(1.0, time / 2.0, (DURATION_SECONDS - time) / 2.0)
    value = max(-0.95, min(0.95, (pad + kick + shimmer) * max(0.0, fade)))
    return int(value * 32_767)


def generate() -> None:
    with wave.open(str(OUTPUT), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        chunk = bytearray()
        for index in range(SAMPLE_RATE * DURATION_SECONDS):
            chunk.extend(struct.pack("<h", sample_at(index)))
            if len(chunk) >= 65_536:
                output.writeframesraw(chunk)
                chunk.clear()
        if chunk:
            output.writeframesraw(chunk)


if __name__ == "__main__":
    generate()
    print(f"Generated {OUTPUT} ({OUTPUT.stat().st_size} bytes)")
