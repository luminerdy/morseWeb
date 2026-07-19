# morseWeb Project Plan

Web-based Morse code learning app derived from [morsePi](https://github.com/luminerdy/morsePi).
Stack: Flask + SQLite on a single EC2 instance. Spacebar is the keyer. Open signup.

Guiding rule: each phase ends with something that runs and has passing tests, mirroring morsePi's regression-bank approach.

---

## Phase 0 — Repo and foundation (1–2 sessions)

Goal: a new `morseWeb` repo with the reusable morsePi logic ported and tested, no web code yet.

- Create `morseWeb` GitHub repo (MIT license, README crediting morsePi as origin).
- Copy over the hardware-independent Python: `morse.py`, learning-gate/progression logic, practice coach, badge derivation, Farnsworth timing math.
- Copy the relevant test files; strip GPIO/mock-pin dependencies. Get the ported tests green with plain `python3 -m unittest`.
- Carry forward the `specs/` requirement-ID format; write `specs/README.md` for the web version (what's in scope, what's explicitly dropped: GPIO, LED, touch flow, systemd station scripts).
- Set up GitHub Actions CI running the test bank on every push (morsePi already has workflows to crib from).

Exit criteria: CI green on ported logic; specs describe the web app's scope.

## Phase 1 — Single-user web app, local (2–4 sessions)

Goal: the full learning experience running on your own machine with the spacebar keyer, one anonymous user, SQLite.

- Flask app skeleton: routes for home, Learn, Send, Read, Listen, Echo, Words, Progress.
- Promote morsePi's spacebar keyer JS from fallback to primary input. Capture keydown/keyup timestamps client-side and send timing events to the server (this preserves the rhythm-history data morsePi collects from GPIO).
- Browser audio via the existing Web Audio playback JS; sidetone on spacebar press.
- Replace `data/students/*.json` and JSONL files with SQLite (SQLAlchemy): tables for `users`, `letter_progress`, `practice_attempts`, `word_attempts`, `timing_events`, `daily_missions`. Write a one-time importer from morsePi's JSON format so existing grandkid progress could be migrated later.
- Port learning gates, Daily Mission, Signal Sprint, badges, and Practice Coach on top of the new data layer.
- Extend the test bank: routes, gates against SQLite, attempt logging, timing summaries.

Exit criteria: you can run the full practice loop locally end-to-end; test bank covers routes and data layer.

## Phase 2 — Accounts and multi-user (2–3 sessions)

Goal: real users with isolated data.

- Auth with Flask-Login + email verification and password reset (SES for email once on AWS; console-printed links in dev).
- Because kids will use this: child accounts created and managed by a parent account, no child email required, parent consent flow. This is the COPPA-relevant piece — design it now, before open signup.
- Roles: admin (you), parent, student. Admin dashboard replaces morsePi's desktop admin reset — per-student reset with backup, plus basic usage view.
- Per-user data isolation enforced in every query; tests that user A cannot read user B's progress.
- CSRF protection, rate limiting on auth endpoints (Flask-WTF, Flask-Limiter), secure session cookies.

Exit criteria: two users can practice concurrently in different browsers with separate progress; isolation tests pass.

## Phase 3 — EC2 deployment (1–2 sessions)

Goal: the app live on AWS at a real domain over HTTPS.

- EC2: single `t4g.small` (Arm, ~$12/mo, plenty for this) running Ubuntu LTS. Security group: 80/443 open, SSH via Session Manager only (no open port 22 — reuse your SSM setup from the morsePi AWS work).
- App served by gunicorn behind nginx; systemd unit for the app (you already have the systemd pattern from morsePi).
- Domain in Route 53, TLS via Let's Encrypt/certbot.
- SQLite backups to S3: adapt morsePi's backup script + add Litestream for continuous replication so a dead instance loses at most seconds of data.
- Deploys: GitHub Actions → SSM run-command that pulls, migrates, restarts. Tag releases.
- CloudWatch agent for logs, disk, memory; alarm on instance health and backup failure.

Exit criteria: HTTPS site live; kill-the-instance restore drill from S3/Litestream succeeds.

## Phase 4 — Open-signup hardening (2–3 sessions)

Goal: safe to let strangers register.

- Terms of service + privacy policy pages (required for COPPA parent-consent language).
- Signup abuse controls: rate limits, email verification required before practice data is stored, optional CAPTCHA.
- Input validation pass on every POST route; dependency audit (`pip-audit`) in CI.
- Load sanity check (e.g., `locust` with ~50 concurrent keyers) — confirms SQLite + gunicorn worker config holds; document the trigger point for moving to RDS Postgres (the SQLAlchemy layer from Phase 1 makes that a config change, not a rewrite).
- Error tracking (Sentry free tier or CloudWatch alarms on 5xx).
- Uptime monitoring and a status/health endpoint.

Exit criteria: a stranger can sign up, a parent can add a child, and abuse vectors are rate-limited and monitored.

## Phase 5 — Growth and morsePi convergence (ongoing)

Ideas, in rough priority order — pick per interest:

- Family/friend messaging: send real Morse messages between users (the original telegraph spirit).
- Pi station sync: grandkid stations upload progress to morseWeb via the S3/IoT channel you already designed, so web and station share one progress record.
- Rhythm Trends and coaching from the timing events collected in Phase 1.
- Leaderboards/classroom mode if usage grows.
- Extract shared Morse/learning logic into a package both morsePi and morseWeb import (only when double-maintenance actually hurts).

---

## What deliberately does not carry over

GPIO key input, LED/speaker station playback, 7-inch touch flow, per-station config and identity scripts, hardware tests, systemd backup timers (replaced by Litestream/S3), desktop admin reset (replaced by web admin).

## Cost estimate

t4g.small (~$12/mo) + Route 53 hosted zone ($0.50/mo) + domain (~$12/yr) + S3/SES (pennies at this scale). Roughly **$15/month**.

## Risk notes

- Spacebar timing in browsers is good (~few ms jitter) but not GPIO-grade; keep Farnsworth tolerances slightly looser than the Pi's and tune from real attempt data.
- SQLite is single-writer; fine for hundreds of users with short writes, but keep all writes fast and use WAL mode. Migration path to Postgres is pre-paid by using SQLAlchemy.
- Open signup + kids means the Phase 2 parent-consent design is not optional — do not launch open signup before Phase 4 completes.
