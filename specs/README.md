# morseWeb Specifications

morseWeb is the web rebuild of [morsePi](https://github.com/luminerdy/morsePi). This directory carries forward morsePi's requirement-ID convention (`MW-` prefix here, e.g. `MW-F-001`).

## Scope

In scope:

- Spacebar keyer as the primary input, with client-side keydown/keyup timing capture
- Browser audio (Web Audio API) for playback, sidetone, and Listen/Echo practice
- All morsePi practice modes: Learn, Send, Read, Listen, Echo, Words
- Learning gates, letter unlock groups, Daily Mission, Signal Sprint, Practice Coach, badges
- Multi-user accounts with parent-managed child accounts (open signup after hardening)
- SQLite storage via SQLAlchemy; deployment on a single EC2 instance

Explicitly out of scope (stays in morsePi):

- GPIO telegraph key input, LED, and USB speaker station playback
- 7-inch touchscreen flow
- Per-station identity/config, systemd services, station backup timers

## Requirement documents

Added per phase. Phase 0 covers only the ported learning core; its behavior is specified by the regression test bank in `tests/`, carried over from morsePi.

| ID | Requirement | Verified by |
| --- | --- | --- |
| MW-F-001 | Text/Morse conversion round-trips A–Z and 0–9 | tests/test_morse.py |
| MW-F-002 | Key timing events are normalized and summarized (dot/dash/gap rhythm) | tests/test_practice_attempts.py |
| MW-F-003 | Letter unlock gates: Learn repetitions, strength, rest, and word practice before next group | tests/test_learning_gates.py |
| MW-F-004 | Daily Mission, Practice Coach, and badges derive from attempt history | tests/test_learning_gates.py |
