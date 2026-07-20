import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import emailer
import storage
from extensions import limiter
from webtest import WebTestCase


class SignupAndVerificationTests(WebTestCase):
    def signup(self, email="new@example.com", password="longenough1"):
        return self.client.post("/signup", data={
            "name": "New Parent",
            "email": email,
            "password": password,
            "confirm": password,
        }, follow_redirects=False)

    def test_signup_creates_unverified_parent_and_sends_link(self):
        response = self.signup()
        self.assertEqual(302, response.status_code)

        user = storage.get_user_by_email("new@example.com")
        self.assertIsNotNone(user)
        self.assertEqual("parent", user["role"])
        self.assertEqual(0, user["email_verified"])
        self.assertIsNotNone(self.last_email_link("/verify/"))

    def test_unverified_parent_cannot_log_in(self):
        self.signup()
        response = self.login("new@example.com", "longenough1")
        self.assertEqual(403, response.status_code)

    def test_verification_link_enables_login(self):
        self.signup()
        link = self.last_email_link("/verify/")
        response = self.client.get(link)
        self.assertEqual(302, response.status_code)

        self.assertEqual(1, storage.get_user_by_email("new@example.com")["email_verified"])
        self.assertEqual(302, self.login("new@example.com", "longenough1").status_code)

    def test_bad_verification_token_rejected(self):
        self.signup()
        self.client.get("/verify/not-a-real-token")
        self.assertEqual(0, storage.get_user_by_email("new@example.com")["email_verified"])

    def test_signup_rejects_short_password(self):
        response = self.signup(password="short")
        self.assertEqual(400, response.status_code)
        self.assertIsNone(storage.get_user_by_email("new@example.com"))

    def test_signup_survives_email_send_failure(self):
        def broken_send(to, subject, body):
            raise RuntimeError("mail backend down")

        original = emailer.send_message
        emailer.send_message = broken_send
        self.addCleanup(lambda: setattr(emailer, "send_message", original))

        response = self.signup()
        self.assertEqual(302, response.status_code)
        self.assertIsNotNone(storage.get_user_by_email("new@example.com"))

    def test_duplicate_email_not_revealed(self):
        self.signup()
        emailer.outbox.clear()
        response = self.signup()
        self.assertEqual(302, response.status_code)
        self.assertEqual([], emailer.outbox)


class LoginTests(WebTestCase):
    def test_login_and_logout(self):
        self.create_parent()
        response = self.login()
        self.assertEqual(302, response.status_code)

        self.assertEqual(200, self.client.get("/practice").status_code)
        self.assertEqual(302, self.client.post("/logout").status_code)
        self.assertEqual(302, self.client.get("/practice").status_code)

    def test_wrong_password_rejected(self):
        self.create_parent()
        response = self.login(password="wrong-password")
        self.assertEqual(401, response.status_code)

    def test_unknown_user_rejected(self):
        response = self.login("nobody@example.com", "whatever123")
        self.assertEqual(401, response.status_code)

    def test_deactivated_user_rejected(self):
        user_id = self.create_parent()
        storage.update_user(user_id, is_active=0)
        response = self.login()
        self.assertEqual(401, response.status_code)


class PasswordResetTests(WebTestCase):
    def test_reset_flow_changes_password(self):
        self.create_parent()
        response = self.client.post("/forgot", data={"email": "parent@example.com"})
        self.assertEqual(302, response.status_code)

        link = self.last_email_link("/reset/")
        self.assertIsNotNone(link)

        response = self.client.post(link, data={
            "password": "brandnewpass1",
            "confirm": "brandnewpass1",
        })
        self.assertEqual(302, response.status_code)

        self.assertEqual(401, self.login(password="pass12345").status_code)
        self.assertEqual(302, self.login(password="brandnewpass1").status_code)

    def test_forgot_does_not_reveal_unknown_email(self):
        response = self.client.post("/forgot", data={"email": "nobody@example.com"})
        self.assertEqual(302, response.status_code)
        self.assertEqual([], emailer.outbox)

    def test_bad_reset_token_rejected(self):
        response = self.client.post("/reset/bogus-token", data={
            "password": "brandnewpass1",
            "confirm": "brandnewpass1",
        })
        self.assertEqual(302, response.status_code)
        self.assertIn("/forgot", response.headers["Location"])


class SecurityHardeningTests(WebTestCase):
    def test_csrf_required_when_enabled(self):
        self.create_parent()
        self.app.config["WTF_CSRF_ENABLED"] = True
        self.addCleanup(lambda: self.app.config.update(WTF_CSRF_ENABLED=False))

        response = self.login()
        self.assertEqual(400, response.status_code)

    def test_csrf_required_on_json_practice_post(self):
        self.logged_in_parent()
        self.app.config["WTF_CSRF_ENABLED"] = True
        self.addCleanup(lambda: self.app.config.update(WTF_CSRF_ENABLED=False))

        response = self.client.post("/practice/result", json={
            "target": "E", "mode": "send", "actual_morse": ".",
        })
        self.assertEqual(400, response.status_code)

    def test_login_rate_limited(self):
        limiter.enabled = True
        self.addCleanup(lambda: setattr(limiter, "enabled", False))
        limiter.reset()

        last_status = None
        for _ in range(12):
            last_status = self.login("nobody@example.com", "wrong").status_code
        self.assertEqual(429, last_status)

    def test_session_cookie_flags(self):
        self.assertTrue(self.app.config["SESSION_COOKIE_HTTPONLY"])
        self.assertEqual("Lax", self.app.config["SESSION_COOKIE_SAMESITE"])


if __name__ == "__main__":
    unittest.main()
