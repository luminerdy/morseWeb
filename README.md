# morseWeb

A web-based Morse code learning app, derived from [morsePi](https://github.com/luminerdy/morsePi) (Pappy's Internet Telegraph). Where morsePi is a Raspberry Pi station with a physical telegraph key, morseWeb targets any computer with a browser: the **spacebar is the keyer**, audio plays through the browser, and the app is hosted on AWS EC2 for multiple users.

## Status: Phase 0

This repo currently contains the hardware-independent learning core ported from morsePi, with a passing test bank. No web app yet — see [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) for the phased roadmap.

Ported from morsePi:

- `morse.py` — text/Morse conversion
- `practice_progress.py` — per-letter, per-mode progress records and scoring
- `practice_attempts.py` — attempt logging, key-timing events, rhythm summaries
- `learning.py` — learning gates, letter unlock groups, Farnsworth timing math, Daily Mission, Practice Coach, badges (extracted from morsePi's `app.py`, minus all GPIO/audio/Flask code)

Deliberately not ported: GPIO key input, LED/speaker playback, touch-screen flow, per-station config, systemd scripts.

## Running tests

```
python3 -m unittest discover -s tests
```

Stdlib only — no dependencies needed for Phase 0.

## License

MIT, same as morsePi.
