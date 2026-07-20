"""Load sanity check: ~50 concurrent spacebar keyers (Phase 4).

Run ON the instance against gunicorn directly, so it exercises the real
production stack (gunicorn workers + SQLite WAL) without nginx/TLS in
the way:

    LOADTEST_EMAIL=loadtest@luminerdy.com LOADTEST_PASSWORD=... \
    locust -f tools/loadtest/locustfile.py --headless -u 50 -r 5 -t 90s \
        -H http://127.0.0.1:8000 --csv /tmp/load

All simulated keyers share one logged-in session (Flask sessions are
client-side cookies), which also makes every write contend on the same
user's progress document - a worst-case for SQLite's single writer.

The login endpoint is rate-limited to 10/min, so we log in ONCE at test
start and hand the session cookie to every simulated user.
"""

import os
import re

import requests
from locust import HttpUser, between, events, task

SHARED = {"cookie": None, "csrf": None}


@events.test_start.add_listener
def login_once(environment, **kwargs):
    host = environment.host.rstrip("/")
    session = requests.Session()

    page = session.get(f"{host}/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    response = session.post(f"{host}/login", data={
        "identifier": os.environ["LOADTEST_EMAIL"],
        "password": os.environ["LOADTEST_PASSWORD"],
        "csrf_token": token,
    }, allow_redirects=False)
    assert response.status_code == 302, f"login failed: {response.status_code}"

    practice = session.get(f"{host}/practice")
    SHARED["csrf"] = re.search(
        r'name="csrf-token" content="([^"]+)"', practice.text).group(1)
    SHARED["cookie"] = session.cookies.get("session")


class Keyer(HttpUser):
    wait_time = between(1.0, 3.0)  # one letter every couple of seconds

    def on_start(self):
        # Send the cookie explicitly per request - cookie-jar domain
        # matching for a bare IP host silently drops it otherwise.
        self.headers = {
            "X-CSRFToken": SHARED["csrf"],
            "Cookie": f"session={SHARED['cookie']}",
        }
        sanity = self.client.get("/practice", headers=self.headers,
                                 allow_redirects=False)
        assert sanity.status_code == 200, f"session not accepted: {sanity.status_code}"

    @task(5)
    def send_letter(self):
        with self.client.post("/practice/result", json={
            "target": "E",
            "mode": "send",
            "actual_morse": ".",
            "timing_events": [
                {"type": "symbol", "symbol": ".", "duration_ms": 95},
            ],
        }, headers=self.headers, catch_response=True) as response:
            if response.status_code == 200 and b'"status"' not in response.content:
                response.failure("no status in payload")

    @task(2)
    def next_prompt(self):
        self.client.post("/practice/next?mode=send", headers=self.headers)

    @task(1)
    def check_progress(self):
        self.client.get("/progress", headers=self.headers,
                        allow_redirects=False)
