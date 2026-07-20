import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import storage
from webtest import WebTestCase


class FamilyTests(WebTestCase):
    def setUp(self):
        super().setUp()
        self.parent_id = self.logged_in_parent()

    def test_parent_creates_child_with_consent(self):
        response = self.add_child()
        self.assertEqual(302, response.status_code)

        child = storage.get_user_by_slug("kiddo")
        self.assertIsNotNone(child)
        self.assertEqual("student", child["role"])
        self.assertEqual(self.parent_id, child["parent_id"])
        self.assertEqual(self.parent_id, child["consent_by"])
        self.assertTrue(child["consent_at"])
        self.assertIsNone(child["email"])

    def test_child_requires_consent(self):
        self.client.post("/family/children", data={
            "username": "kiddo", "name": "Kiddo", "password": "dots",
        })
        self.assertIsNone(storage.get_user_by_slug("kiddo"))

    def test_child_username_length_capped(self):
        self.client.post("/family/children", data={
            "username": "k" * 40, "name": "Kiddo", "password": "dots",
            "consent": "yes",
        })
        self.assertIsNone(storage.get_user_by_slug("k" * 30))

    def test_child_logs_in_with_username(self):
        self.add_child()
        child_client = self.app.test_client()
        response = self.login("kiddo", "dots", client=child_client)
        self.assertEqual(302, response.status_code)
        self.assertEqual(200, child_client.get("/practice").status_code)

    def test_child_cannot_open_family_or_admin(self):
        self.add_child()
        child_client = self.app.test_client()
        self.login("kiddo", "dots", client=child_client)
        self.assertEqual(403, child_client.get("/family").status_code)
        self.assertEqual(403, child_client.get("/admin").status_code)

    def test_parent_resets_child_password(self):
        self.add_child()
        child = storage.get_user_by_slug("kiddo")
        self.client.post(f"/family/children/{child['id']}/password", data={"password": "dashes"})

        child_client = self.app.test_client()
        self.assertEqual(401, self.login("kiddo", "dots", client=child_client).status_code)
        self.assertEqual(302, self.login("kiddo", "dashes", client=child_client).status_code)

    def test_parent_pauses_child_login(self):
        self.add_child()
        child = storage.get_user_by_slug("kiddo")
        self.client.post(f"/family/children/{child['id']}/active")

        child_client = self.app.test_client()
        self.assertEqual(401, self.login("kiddo", "dots", client=child_client).status_code)

    def test_parent_cannot_manage_another_parents_child(self):
        self.add_child()
        child = storage.get_user_by_slug("kiddo")

        other_client = self.app.test_client()
        self.create_parent(email="other@example.com", slug="other-parent")
        self.login("other@example.com", client=other_client)

        response = other_client.post(
            f"/family/children/{child['id']}/password", data={"password": "hacked"})
        self.assertEqual(404, response.status_code)

        child_client = self.app.test_client()
        self.assertEqual(302, self.login("kiddo", "dots", client=child_client).status_code)


class AdminTests(WebTestCase):
    def setUp(self):
        super().setUp()
        self.admin_id = self.logged_in_parent(
            email="admin@example.com", slug="admin", role="admin")

    def test_parent_cannot_open_admin(self):
        parent_client = self.app.test_client()
        self.create_parent(email="parent@example.com", slug="parent")
        self.login("parent@example.com", client=parent_client)
        self.assertEqual(403, parent_client.get("/admin").status_code)

    def test_admin_dashboard_lists_users(self):
        self.create_parent(email="parent@example.com", slug="parent", name="Pat Parent")
        response = self.client.get("/admin")
        self.assertEqual(200, response.status_code)
        self.assertIn(b"Pat Parent", response.data)

    def test_admin_reset_backs_up_then_clears_progress(self):
        parent_client = self.app.test_client()
        parent_id = self.create_parent(email="parent@example.com", slug="parent")
        self.login("parent@example.com", client=parent_client)
        parent_client.post("/practice/result", json={
            "target": "E", "mode": "send", "actual_morse": ".",
        })

        storage.set_current_user(parent_id)
        self.assertEqual(1, len(storage.load_attempts("practice")))

        response = self.client.post(f"/admin/users/{parent_id}/reset")
        self.assertEqual(302, response.status_code)

        storage.set_current_user(parent_id)
        self.assertEqual(0, len(storage.load_attempts("practice")))
        self.assertIsNone(storage.get_document("practice_progress"))

        backups = storage.list_backups(parent_id)
        self.assertEqual(1, len(backups))
        self.assertIn("admin reset by admin", backups[0]["reason"])

    def test_admin_cannot_deactivate_self(self):
        self.client.post(f"/admin/users/{self.admin_id}/active")
        self.assertEqual(1, storage.get_user(self.admin_id)["is_active"])

    def test_admin_deactivates_and_reactivates_user(self):
        parent_id = self.create_parent(email="parent@example.com", slug="parent")
        self.client.post(f"/admin/users/{parent_id}/active")
        self.assertEqual(0, storage.get_user(parent_id)["is_active"])
        self.client.post(f"/admin/users/{parent_id}/active")
        self.assertEqual(1, storage.get_user(parent_id)["is_active"])


if __name__ == "__main__":
    unittest.main()
