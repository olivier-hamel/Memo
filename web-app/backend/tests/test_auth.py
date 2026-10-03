import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

from fastapi.testclient import TestClient

from backend.auth import Accounts, SESSION_SECONDS
from backend.main import COOKIE, create_app
from backend.study_engine import StudySession

PASSWORD = "temporary-passphrase-123"
NEW_PASSWORD = "a-new-private-passphrase-456"
HEADERS = {"Origin": "https://memo.test", "X-Memo-Request": "1"}


class AccountApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.now = 1000.0
        self.accounts = Accounts(self.directory, clock=lambda: self.now)
        self.oli = self.accounts.create("oli", "Oli", PASSWORD, must_change=False)
        self.max = self.accounts.create("max", "Max", PASSWORD, must_change=False)
        self.app = self.make_app()
        self.client = TestClient(self.app, base_url="https://memo.test").__enter__()

    def make_app(self):
        return create_app(auth_enabled=True, data_dir=self.directory, require_https=True,
                          clock=lambda: self.now, raw_cards=[("A", "Alpha"), ("B", "Beta")])

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def login(self, name="oli", password=PASSWORD, client=None):
        return (client or self.client).post("/api/auth/login", json={"username": name, "password": password}, headers=HEADERS)

    def action(self, client, kind, **values):
        state = client.get("/api/state").json()
        return client.post("/api/actions", json={"type": kind, "revision": state["revision"], **values}, headers=HEADERS)

    def test_auth_required_and_https_cookie(self):
        self.assertEqual(self.client.get("/api/state").status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        response = self.login()
        self.assertEqual(response.status_code, 200)
        cookie = response.headers["set-cookie"].lower()
        for flag in ("httponly", "secure", "samesite=strict", "max-age=604800"):
            self.assertIn(flag, cookie)
        self.assertNotIn("password_hash", response.text)
        self.assertNotIn(PASSWORD, response.text)
        self.assertEqual(self.client.get("/api/state").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").headers["cache-control"], "no-store")

    def test_http_credentials_and_forged_forwarding_are_rejected(self):
        with TestClient(self.make_app(), base_url="http://memo.test") as client:
            response = client.post("/api/auth/login", json={"username": "oli", "password": PASSWORD},
                                   headers={**HEADERS, "X-Forwarded-Proto": "https"})
            self.assertEqual(response.status_code, 426)
            self.assertEqual(client.get("/api/health").status_code, 200)

    def test_cross_origin_and_missing_request_header_are_rejected(self):
        for headers in ({}, {"Origin": "https://evil.test", "X-Memo-Request": "1"}, {"Origin": "https://memo.test"}):
            self.assertEqual(self.client.post("/api/auth/login", json={"username": "oli", "password": PASSWORD}, headers=headers).status_code, 403)
        self.login()
        self.assertEqual(self.client.post("/api/auth/logout", json={}, headers={**HEADERS, "Origin": "https://evil.test"}).status_code, 403)
        self.assertEqual(self.client.get("/api/state").status_code, 200)

    def test_failed_login_throttling_and_window_expiry(self):
        for _ in range(10):
            self.assertEqual(self.login(password="incorrect").status_code, 401)
        self.assertEqual(self.login().status_code, 429)
        self.now += 901
        self.assertEqual(self.login().status_code, 200)

    def test_logout_and_expiry_revoke_session(self):
        self.login()
        token = self.client.cookies.get(COOKIE)
        self.assertEqual(self.client.post("/api/auth/logout", json={}, headers=HEADERS).status_code, 200)
        self.assertIsNone(self.accounts.resolve(token))
        self.login()
        self.now += SESSION_SECONDS
        self.assertEqual(self.client.get("/api/state").status_code, 401)

    def test_users_have_independent_state_and_revision(self):
        self.login()
        self.action(self.client, "flip")
        self.action(self.client, "grade", correct=True)
        oli_state = self.client.get("/api/state").json()
        with TestClient(self.make_app(), base_url="https://memo.test") as other:
            self.login("max", client=other)
            max_state = other.get("/api/state").json()
            self.assertEqual(max_state["correct"], 0)
            self.assertNotEqual(oli_state["revision"], max_state["revision"])
            response = other.post("/api/actions", json={"type": "reset", "revision": oli_state["revision"]}, headers=HEADERS)
            self.assertEqual(response.status_code, 409)
            self.action(other, "settings", typed=True)
        self.assertEqual(self.client.get("/api/state").json()["correct"], 1)
        self.assertFalse(self.client.get("/api/state").json()["typed_recall"])

    def test_password_change_forces_new_credentials_and_revokes_all_sessions(self):
        self.accounts.set_password(self.oli["id"], PASSWORD, must_change=True)
        path = self.directory / "bootstrap" / (self.oli["id"] + ".txt")
        path.parent.mkdir()
        path.write_text(PASSWORD)
        self.login()
        first_token = self.client.cookies.get(COOKIE)
        self.assertEqual(self.client.get("/api/state").status_code, 403)
        self.assertTrue(self.client.get("/api/auth/me").json()["user"]["must_change_password"])
        response = self.client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}, headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["user"]["must_change_password"])
        self.assertIsNone(self.accounts.resolve(first_token))
        self.assertFalse(path.exists())
        self.assertEqual(self.client.get("/api/state").status_code, 200)
        self.assertEqual(self.login(password=PASSWORD).status_code, 401)
        self.assertEqual(self.login(password=NEW_PASSWORD).status_code, 200)

    def test_restart_resumes_user_save_and_existing_session(self):
        self.login()
        self.action(self.client, "flip")
        self.action(self.client, "grade", correct=True)
        before = self.client.get("/api/state").json()
        with TestClient(self.make_app(), base_url="https://memo.test") as restarted:
            restarted.cookies.update(self.client.cookies)
            after = restarted.get("/api/state").json()
            self.assertEqual(after["correct"], before["correct"])
            self.assertEqual(after["question"]["card_id"], before["question"]["card_id"])
            self.assertNotEqual(after["revision"], before["revision"])

    def test_failed_save_rolls_back_only_this_user(self):
        self.login()
        self.action(self.client, "flip")
        before = self.client.get("/api/state").json()
        with patch("backend.controller.os.replace", side_effect=OSError("disk full")):
            self.assertEqual(self.action(self.client, "grade", correct=True).status_code, 503)
        self.assertEqual(self.client.get("/api/state").json(), before)

    def test_invalid_save_does_not_prevent_other_users_from_studying(self):
        path = self.accounts.progress_path(self.oli["id"])
        path.parent.mkdir(parents=True)
        path.write_text('{"version":42}')
        self.login()
        self.assertEqual(self.client.get("/api/state").status_code, 503)
        self.assertEqual(path.read_text(), '{"version":42}')
        self.login("max")
        self.assertEqual(self.client.get("/api/state").status_code, 200)

    def test_import_cli_validates_and_refuses_replacement(self):
        cards = json.loads((Path(__file__).parents[1] / "data" / "flashcards.json").read_text())
        source = self.directory / "source.json"
        source.write_text(json.dumps(StudySession(cards).to_dict()))
        before = source.read_bytes()
        command = [sys.executable, "-m", "backend.accounts", "--data-dir", str(self.directory), "import-progress", "oli", str(source)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        saved = self.accounts.progress_path(self.oli["id"]).read_bytes()
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertEqual(self.accounts.progress_path(self.oli["id"]).read_bytes(), saved)
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse(self.accounts.progress_path(self.max["id"]).exists())

    def test_cli_generated_password_is_private_and_not_printed(self):
        command = [sys.executable, "-m", "backend.accounts", "--data-dir", str(self.directory),
                   "create", "test_cli", "--display-name", "Test", "--generate-password"]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        user = self.accounts.user("test_cli")
        path = self.directory / "bootstrap" / (user["id"] + ".txt")
        password = path.read_text().strip()
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(password, result.stdout)
        self.assertIsNotNone(self.accounts.login("test_cli", password, "localhost"))
