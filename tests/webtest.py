"""Shared base for tests that drive the Flask app.

CSRF and rate limiting are disabled by default so flow tests stay
readable; the dedicated security tests re-enable them per test.
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from werkzeug.security import generate_password_hash

import emailer
import storage
from extensions import limiter

PARENT_EMAIL = "parent@example.com"
PARENT_PASSWORD = "pass12345"


class WebTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as app_module
        cls.app_module = app_module
        cls.app = app_module.app

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        storage.configure(Path(self.temp_dir.name) / "morseweb.sqlite3")
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False
        limiter.enabled = False
        emailer.outbox.clear()
        self.client = self.app.test_client()

    def tearDown(self):
        storage.configure(Path("data/morseweb.sqlite3"))
        self.temp_dir.cleanup()

    # --- account helpers ------------------------------------------------

    def create_parent(self, email=PARENT_EMAIL, password=PARENT_PASSWORD,
                      name="Parent", slug=None, verified=True, role="parent"):
        return storage.create_user(
            slug=slug or email.split("@")[0].replace(".", ""),
            name=name,
            email=email,
            password_hash=generate_password_hash(password),
            role=role,
            email_verified=verified,
        )

    def login(self, identifier=PARENT_EMAIL, password=PARENT_PASSWORD, client=None):
        client = client or self.client
        return client.post(
            "/login",
            data={"identifier": identifier, "password": password},
            follow_redirects=False,
        )

    def logged_in_parent(self, email=PARENT_EMAIL, password=PARENT_PASSWORD, **kwargs):
        user_id = self.create_parent(email=email, password=password, **kwargs)
        response = self.login(email, password)
        assert response.status_code == 302, response.data
        return user_id

    def add_child(self, username="kiddo", name="Kiddo", password="dots", client=None):
        client = client or self.client
        return client.post("/family/children", data={
            "username": username,
            "name": name,
            "password": password,
            "consent": "yes",
        }, follow_redirects=False)

    # --- email helpers --------------------------------------------------

    def last_email_link(self, path_prefix):
        for message in reversed(emailer.outbox):
            match = re.search(rf"({re.escape(path_prefix)}[^\s]+)", message["body"])
            if match:
                return match.group(1)
        return None
