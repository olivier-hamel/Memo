import copy
import json
import os
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError

from backend.auth import Accounts
from backend.controller import WebStudy
from backend.decks import DEFAULT_SET_ID, DeckError, MongoDecks
from backend.main import create_app

PASSWORD = "a-test-passphrase-12345"
HEADERS = {"Origin": "https://memo.test", "X-Memo-Request": "1"}
CARDS = [{"term": "Question A", "definition": "Réponse A"}, {"term": "Question B", "definition": "Réponse B"}]


class DeckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        if os.environ.get("MEMO_TEST_MONGODB_URI"):
            self.mongo = MongoClient(os.environ["MEMO_TEST_MONGODB_URI"], serverSelectionTimeoutMS=5000)
        else:
            import mongomock
            self.mongo = mongomock.MongoClient()
        self.dbname = os.environ.get("MEMO_TEST_DATABASE", "memo_validation_" + uuid.uuid4().hex)
        self.collection_name = "memo_validation_" + uuid.uuid4().hex
        self.repository = MongoDecks(self.mongo[self.dbname][self.collection_name])
        self.accounts = Accounts(self.directory)
        self.oli = self.accounts.create("oli", "Oli", PASSWORD, must_change=False)
        self.max = self.accounts.create("max", "Max", PASSWORD, must_change=False)
        self.repository.import_default(self.oli)
        self.client = TestClient(self.app(), base_url="https://memo.test").__enter__()
        self.login()

    def app(self):
        return create_app(auth_enabled=True, require_https=True, data_dir=self.directory, deck_repository=self.repository)

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.mongo[self.dbname].drop_collection(self.collection_name)
        self.mongo.close()
        self.temp.cleanup()

    def login(self, name="oli", client=None):
        return (client or self.client).post("/api/auth/login", json={"username": name, "password": PASSWORD}, headers=HEADERS)

    def create(self):
        result = self.client.post("/api/sets", json={"title": "Mon ensemble", "description": "Essai", "cards": CARDS}, headers=HEADERS)
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()

    def query(self, deck, version=1):
        return f'?set_id={deck["id"]}&version={version}'

    def grade(self, query=""):
        state = self.client.get("/api/state" + query).json()
        flip = self.client.post("/api/actions" + query, json={"type": "flip", "revision": state["revision"]}, headers=HEADERS)
        self.assertEqual(flip.status_code, 200, flip.text)
        result = self.client.post("/api/actions" + query, json={"type": "grade", "correct": True, "revision": flip.json()["revision"]}, headers=HEADERS)
        self.assertEqual(result.status_code, 200, result.text)

    def edit(self, deck, cards=None, title=None):
        return self.client.post('/api/sets/' + deck["id"], json={"title": title or deck["title"], "description": deck["description"],
            "cards": cards or deck["cards"], "revision": deck["revision"]}, headers=HEADERS)

    def test_create_list_get_and_personal_study(self):
        deck = self.create()
        self.assertTrue(deck["editable"])
        self.assertFalse(deck["shared"])
        self.assertEqual(self.client.get('/api/sets/' + deck["id"]).json()["cards"], CARDS)
        self.assertEqual(len(self.client.get('/api/sets').json()["sets"]), 2)
        self.grade(self.query(deck))
        self.assertEqual(self.client.get('/api/state' + self.query(deck)).json()["correct"], 1)
        self.assertEqual(self.client.get('/api/state').json()["correct"], 0)

    def test_other_account_cannot_read_edit_or_study_private_set(self):
        deck = self.create()
        self.login("max")
        self.assertEqual(len(self.client.get('/api/sets').json()["sets"]), 1)
        self.assertEqual(self.client.get('/api/sets/' + deck["id"]).status_code, 404)
        self.assertEqual(self.edit(deck).status_code, 404)
        self.assertEqual(self.client.get('/api/state' + self.query(deck)).status_code, 404)

    def test_shared_set_is_readable_but_only_owner_can_edit(self):
        deck = self.client.get('/api/sets/' + DEFAULT_SET_ID).json()
        self.login("max")
        self.assertEqual(self.client.get('/api/sets/' + DEFAULT_SET_ID).status_code, 200)
        self.assertEqual(self.edit(deck).status_code, 403)

    def test_edit_versions_preserve_prior_cards_and_progress(self):
        deck = self.create()
        self.grade(self.query(deck))
        edited = self.edit(deck, cards=[{**CARDS[0], "definition": "Nouvelle réponse"}, CARDS[1]])
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["latest_version"], 2)
        self.assertEqual(self.client.get('/api/sets/' + deck["id"] + '?version=1').json()["cards"], CARDS)
        self.assertEqual(self.client.get('/api/state' + self.query(deck, 1)).json()["correct"], 1)
        self.assertEqual(self.client.get('/api/state' + self.query(deck, 2)).json()["correct"], 0)
        self.grade(self.query(deck, 2))
        self.assertEqual(self.client.get('/api/state' + self.query(deck, 1)).json()["correct"], 1)

    def test_title_changes_do_not_reset_card_version(self):
        deck = self.create()
        self.grade(self.query(deck))
        result = self.edit(deck, title="Un nouveau titre")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["latest_version"], 1)
        self.assertEqual(self.client.get('/api/state' + self.query(deck)).json()["correct"], 1)

    def test_stale_editor_and_stale_study_are_rejected(self):
        deck = self.create()
        self.assertEqual(self.edit(deck, title="Premier titre").status_code, 200)
        self.assertEqual(self.edit(deck, title="Titre périmé").status_code, 409)
        before = self.client.get('/api/state' + self.query(deck)).json()
        self.grade(self.query(deck))
        stale = self.client.post('/api/actions' + self.query(deck), json={"type": "grade", "correct": True,
            "revision": before["revision"]}, headers=HEADERS)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.client.get('/api/state' + self.query(deck)).json()["correct"], 1)

    def test_atomic_concurrent_edit_has_one_winner(self):
        deck = self.create()
        find = self.repository._find
        barrier = threading.Barrier(2)
        local = threading.local()
        def concurrent_find(*args):
            result = find(*args)
            if not getattr(local, "read", False):
                local.read = True
                barrier.wait(timeout=10)
            return result
        def save(title):
            try:
                self.repository.save(self.oli, title, "", copy.deepcopy(CARDS), deck["id"], deck["revision"])
                return 200
            except DeckError as error:
                return error.status
        with patch.object(self.repository, '_find', side_effect=concurrent_find), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(save, title) for title in ["Premier", "Second"]]
            self.assertEqual(sorted(f.result() for f in futures), [200, 409])

    def test_validation_rejects_empty_duplicate_and_identity_fields(self):
        for cards in [[], [{"term": " ", "definition": "Réponse"}], CARDS + [CARDS[0]]]:
            result = self.client.post('/api/sets', json={"title": "Test", "cards": cards}, headers=HEADERS)
            self.assertIn(result.status_code, [400, 422])
        result = self.client.post('/api/sets', json={"title": "Test", "cards": CARDS, "owner_id": self.max["id"], "shared": True}, headers=HEADERS)
        self.assertEqual(result.status_code, 422)
        self.assertEqual(self.client.get('/api/sets/not-a-valid-id').status_code, 404)
        self.assertEqual(self.client.get('/api/state?set_id=../outside&version=1').status_code, 404)
        self.assertEqual(self.client.get('/api/state?set_id=' + DEFAULT_SET_ID + '&version=0').status_code, 422)
        self.assertEqual(self.client.get('/api/sets/' + DEFAULT_SET_ID + '?version=2000').status_code, 404)

    def test_auth_password_change_and_origin_guards_apply_to_editor(self):
        self.client.post('/api/auth/logout', json={}, headers=HEADERS)
        self.assertEqual(self.client.get('/api/sets').status_code, 401)
        self.login()
        self.assertEqual(self.client.post('/api/sets', json={"title": "Test", "cards": CARDS},
            headers={**HEADERS, "Origin": "https://evil.test"}).status_code, 403)
        self.accounts.set_password(self.oli["id"], PASSWORD, must_change=True)
        self.login()
        self.assertEqual(self.client.get('/api/sets').status_code, 403)

    def test_default_import_is_idempotent_and_preserves_legacy_progress(self):
        original = self.client.get('/api/sets/' + DEFAULT_SET_ID).json()
        self.grade()
        path = self.accounts.progress_path(self.oli["id"])
        saved = path.read_bytes()
        self.repository.import_default(self.oli)
        self.assertEqual(original, self.client.get('/api/sets/' + DEFAULT_SET_ID).json())
        self.assertEqual(saved, path.read_bytes())
        changed = [{**original["cards"][0], "definition": "Une nouvelle définition"}, *original["cards"][1:]]
        self.assertEqual(self.edit(original, changed).status_code, 200)
        self.repository.import_default(self.oli)
        self.assertEqual(self.client.get('/api/sets/' + DEFAULT_SET_ID).json()["latest_version"], 2)
        self.assertEqual(self.client.get('/api/state').json()["correct"], 1)

    def test_restart_resumes_per_set_and_per_version(self):
        deck = self.create()
        self.grade(self.query(deck))
        with TestClient(self.app(), base_url='https://memo.test') as restarted:
            restarted.cookies.update(self.client.cookies)
            self.assertEqual(restarted.get('/api/state' + self.query(deck)).json()["correct"], 1)
            self.assertEqual(restarted.get('/api/state').json()["correct"], 0)

    def test_mongo_failure_does_not_change_existing_progress(self):
        self.grade()
        saved = self.accounts.progress_path(self.oli["id"]).read_bytes()
        with patch.object(self.repository.collection, 'find_one', side_effect=ServerSelectionTimeoutError('private URI')):
            result = self.client.get('/api/state')
            self.assertEqual(result.status_code, 503)
            self.assertNotIn('private URI', result.text)
        self.assertEqual(saved, self.accounts.progress_path(self.oli["id"]).read_bytes())

    def test_large_editor_payload_is_rejected(self):
        cards = [{"term": str(i), "definition": "x" * 12000} for i in range(200)]
        result = self.client.post('/api/sets', json={"title": "Trop grand", "cards": cards}, headers=HEADERS)
        self.assertEqual(result.status_code, 413)
