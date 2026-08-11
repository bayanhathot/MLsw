# Zonix demo audio

`zonix-demo.wav` is original procedural audio generated from sine waves by
`generate_demo.py`. It contains no third-party sample or recording.

Regenerate it from the backend directory with:

```powershell
python app/static/audio/generate_demo.py
```

Format: 60 seconds, mono, 22.05 kHz, signed 16-bit PCM WAV.

Verified output on the supported project CPython/build:

- Size: 2,646,044 bytes
- SHA-256: `caf323a5be3e43371d0b50b8f31e2815e8eb7a7bb2974046b26406b0cca6bc4c`

Floating-point `libm` implementations can differ across platforms; verify the
hash above when regenerating for a release.
