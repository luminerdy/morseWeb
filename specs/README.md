# morseWeb Specifications

morseWeb is the web rebuild of [morsePi](https://github.com/luminerdy/morsePi). This directory carries forward morsePi's requirement-ID convention (`MW-` prefix here, e.g. `MW-F-001`).

## Scope

In scope:

- Spacebar keyer as the primary input, with client-side keydown/keyup timing capture
- Browser audio (Web Audio API) for playback, sidetone, and Listen/Echo practice
- All morsePi practice modes: Learn, Send, Read, Listen, Echo, Words
- Learning gates, letter unlock groups, Daily Mission, Signal Sprint, Practice Coach, badges
- Multi-user accounts with parent-managed child accounts (open signup after hardening)
- SQLite storage (plain sqlite3, all SQL in storage.py); deployment on a single EC2 instance

Explicitly out of scope (stays in morsePi):

- GPIO telegraph key input, LED, and USB speaker station playback
- 7-inch touchscreen flow
- Per-station identity/config, systemd services, station backup timers

## Requirement documents

Added per phase; behavior is specified by the regression test bank in `tests/`.

| ID | Requirement | Verified by |
| --- | --- | --- |
| MW-F-001 | Text/Morse conversion round-trips A–Z and 0–9 | tests/test_morse.py |
| MW-F-002 | Key timing events are normalized and summarized (dot/dash/gap rhythm) | tests/test_practice_attempts.py |
| MW-F-003 | Letter unlock gates: Learn repetitions, strength, rest, and word practice before next group | tests/test_learning_gates.py |
| MW-F-004 | Daily Mission, Practice Coach, and badges derive from attempt history | tests/test_learning_gates.py |
| MW-F-005 | Home page converts text to Morse and plays it in the browser | tests/test_routes.py |
| MW-F-006 | All five practice modes render and serve prompts | tests/test_routes.py |
| MW-F-007 | Attempts are checked server-side; the client cannot forge correctness | tests/test_routes.py |
| MW-F-008 | Attempts against locked letters are ignored | tests/test_routes.py |
| MW-F-009 | Per-user Farnsworth timing settings persist and are clamped to safe ranges | tests/test_routes.py |
| MW-F-010 | Word practice unlocks only after S/O gate; words are decoded and logged | tests/test_routes.py |
| MW-D-001 | All storage is SQLite; attempts preserve raw key-timing events | tests/test_routes.py, storage.py |
| MW-D-002 | Data is isolated per user in every query; no cross-request user state | tests/test_isolation.py |
| MW-D-003 | morsePi student data imports losslessly | scripts/import_morsepi_data.py |
| MW-D-004 | Phase 1 databases upgrade in place without data loss | tests/test_migration.py |
| MW-A-001 | Adults sign up with email; login requires a verified email | tests/test_auth.py |
| MW-A-002 | Password reset uses expiring signed tokens; emails never reveal whether an address is registered | tests/test_auth.py |
| MW-A-003 | Child accounts are parent-created with recorded consent, username login, and no child email (COPPA design) | tests/test_family_admin.py |
| MW-A-004 | Roles gate access: students get practice only, parents manage their own children, admin manages all | tests/test_family_admin.py |
| MW-A-005 | Admin per-student reset snapshots to progress_backups before deleting | tests/test_family_admin.py |
| MW-S-001 | All POST routes require CSRF (form token or X-CSRFToken header) | tests/test_auth.py |
| MW-S-002 | Auth endpoints are rate-limited | tests/test_auth.py |
| MW-S-003 | Session cookies are HttpOnly and SameSite=Lax (Secure flag via MORSEWEB_SECURE_COOKIES) | tests/test_auth.py |
| MW-O-001 | /healthz answers without auth and verifies database access | tests/test_routes.py |
| MW-O-002 | Deploys are repeatable: gunicorn+nginx+systemd configs and SSM deploy script live in deploy/ | deploy/, .github/workflows/deploy.yml |
| MW-O-003 | Database survives instance loss: Litestream continuous replication + nightly S3 snapshots; restore drill documented | deploy/litestream.yml, deploy/backup_to_s3.sh, docs/DEPLOY.md |
