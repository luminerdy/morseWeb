# morseWeb

A web-based Morse code learning app, derived from [morsePi](https://github.com/luminerdy/morsePi) (Pappy's Internet Telegraph). Where morsePi is a Raspberry Pi station with a physical telegraph key, morseWeb targets any computer with a browser: the **spacebar is the keyer**, audio plays through the browser, and the app is hosted on AWS EC2 for multiple users.

## Status: Phase 1

The full practice experience runs locally as a single-user Flask app with SQLite storage. See [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) for the phased roadmap (Phase 2: accounts, Phase 3: EC2).

```
pip install -r requirements.txt
python3 app.py
```

Then open http://localhost:5000. The spacebar is the keyer: short press = dot, long press = dash. Home converts text to Morse and plays it; Practice has Learn, Send, Read, Listen, and Echo modes with the full morsePi learning-gate progression; Progress shows per-letter detail.

Data lives in `data/morseweb.sqlite3`. To bring over progress from a morsePi station:

```
python3 scripts/import_morsepi_data.py /path/to/morsePi/data/students/<student>
```

Ported from morsePi:

- `morse.py` — text/Morse conversion
- `practice_progress.py` — per-letter, per-mode progress records and scoring
- `practice_attempts.py` — attempt logging, key-timing events, rhythm summaries
- `learning.py` — learning gates, letter unlock groups, Farnsworth timing math, Daily Mission, Practice Coach, badges (extracted from morsePi's `app.py`, minus all GPIO/audio code)
- `app.py` — Flask routes (home, practice modes, progress, timing settings)
- `storage.py` — SQLite storage: per-user JSON documents + append-only attempt log with key-timing events; all SQL isolated here
- `templates/`, `static/` — morsePi's desktop UI with the spacebar keyer promoted to primary input and all station/touch controls removed

Deliberately not ported: GPIO key input, LED/speaker playback, touch-screen flow, per-station config, systemd scripts.

## Running tests

```
python3 -m unittest discover -s tests
```

The bank covers Morse conversion, timing-event summaries, learning gates, route behavior, server-side answer checking, and per-user data isolation.

## License

MIT, same as morsePi.
