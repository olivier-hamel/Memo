import copy
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import mongomock
from pypdf import PdfReader, PdfWriter
from fastapi.testclient import TestClient

from backend.auth import Accounts
from backend.card_validation import (COUNT_URL, COVERAGE_SCHEMA, FILE_ROOT, GEMINI_URL,
    MAX_INPUT_TOKENS, MAX_PDF_BYTES, PROJECT_TOO_LARGE, UPLOAD_URL, validate_coverage)
from backend.decks import DeckError, MongoDecks
from backend.gemini_requests import GeminiRequests
from backend.main import create_app
from backend.reference_documents import ReferenceDocuments
from backend.tests.document_fixtures import course_pdf

CARDS = [{"term": "Question existante ?", "definition": "Réponse déjà couverte."}]
PROPOSAL = {"term": "Nouvelle question ?", "definition": "Information manquante.",
    "document_id": "doc1", "page": 2, "evidence": "Notes de la deuxième slide.",
    "missing_information": "Cette information ne figure dans aucune carte."}


def generated(result, finish="STOP"):
    return httpx.Response(200, json={"candidates": [{"finishReason": finish,
        "content": {"parts": [{"text": json.dumps(result)}]}}]})


class ValidationNetworkTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        pdf = course_pdf(Path(self.temp.name) / "Cours.pdf")
        self.documents = [{"id": "doc1", "name": "Cours.pptx", "path": pdf, "page_count": 3,
            "notes": ["", "Notes de la deuxième slide.", ""], "comments": [[], [{"text": "Précision du professeur."}], []]},
            {"id": "doc2", "name": "Chapitre.pdf", "path": pdf, "page_count": 3, "notes": [], "comments": []}]
        self.cards = copy.deepcopy(CARDS)
        self.calls, self.payloads, self.progress = [], {}, []
        self.result = {"analysis_complete": True, "project_too_large": False, "proposals": [copy.deepcopy(PROPOSAL)]}
        self.error_status = None
        self.error_stage = "generate"
        self.finish = "STOP"
        self.processing = False
        self.poll_status = None
        self.upload_target = UPLOAD_URL + "?session=1"
        self.count = 100
        self.coordinator = GeminiRequests(rpm=0, tpm=0, retry_limit=0)

    async def run_validation(self):
        def handle(request):
            self.calls.append(request)
            self.assertEqual(request.headers["x-goog-api-key"], "test-secret")
            self.assertNotIn("test-secret", str(request.url))
            if str(request.url) == UPLOAD_URL:
                return httpx.Response(200, headers={"x-goog-upload-url": self.upload_target})
            if "session=1" in str(request.url):
                self.assertTrue(request.content.startswith(b"%PDF-"))
                number = sum("session=1" in str(call.url) for call in self.calls)
                return httpx.Response(200, json={"file": {"name": f"files/pdf{number}",
                    "uri": FILE_ROOT + f"files/pdf{number}", "state": "PROCESSING" if self.processing else "ACTIVE"}})
            if request.method == "DELETE":
                return httpx.Response(200, json={})
            if request.method == "GET":
                if self.poll_status:
                    return httpx.Response(self.poll_status)
                return httpx.Response(200, json={"uri": str(request.url), "state": "ACTIVE"})
            stage = "count" if str(request.url) == COUNT_URL else "generate"
            self.assertIn(str(request.url), (COUNT_URL, GEMINI_URL))
            self.payloads.setdefault(stage, []).append(json.loads(request.content))
            if self.error_status and self.error_stage == stage:
                return httpx.Response(self.error_status)
            if stage == "count":
                return httpx.Response(200, json={"totalTokens": self.count})
            return generated(self.result, self.finish)
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with patch("backend.card_validation.api_key", return_value="test-secret"), patch("backend.card_validation.httpx.AsyncClient", return_value=client):
            return await validate_coverage(self.cards, self.documents, requests=self.coordinator,
                cache_directory=getattr(self, "cache_directory", None), progress=self.progress.append)

    def assert_cleaned(self):
        uploaded = sum("session=1" in str(call.url) for call in self.calls)
        deleted = [str(call.url) for call in self.calls if call.method == "DELETE"]
        self.assertEqual(len(set(deleted)), uploaded)
        self.assertEqual(len(deleted), uploaded)

    async def test_full_pdfs_cards_notes_and_comments_are_sent_in_one_generation(self):
        result = await self.run_validation()
        self.assertEqual(result, {"covered": False, "proposals": [PROPOSAL], "checked_pages": 6, "checked_cards": 1})
        self.assertEqual(len(self.payloads["generate"]), 1)
        self.assertEqual(len(self.payloads["count"]), 1)
        payload = self.payloads["generate"][0]
        parts = payload["contents"][0]["parts"]
        context = json.loads(parts[0]["text"])
        self.assertEqual(context["cards"], self.cards)
        self.assertEqual([doc["id"] for doc in context["documents"]], ["doc1", "doc2"])
        self.assertEqual(context["documents"][0]["annotations"][1]["notes"], "Notes de la deuxième slide.")
        self.assertEqual(context["documents"][0]["annotations"][1]["comments"][0]["text"], "Précision du professeur.")
        self.assertEqual(sum("fileData" in part for part in parts), 2)
        self.assertEqual(json.loads(parts[1]["text"])["document_id"], "doc1")
        self.assertEqual(json.loads(parts[3]["text"])["document_id"], "doc2")
        counted = self.payloads["count"][0]["generateContentRequest"].copy()
        self.assertEqual(counted.pop("model"), "models/gemini-3.5-flash-lite")
        self.assertEqual(counted, payload)
        self.assertEqual(payload["generationConfig"]["responseJsonSchema"], COVERAGE_SCHEMA)
        self.assert_cleaned()

    async def test_long_pdf_is_not_split_and_all_300_cards_are_sent(self):
        path = Path(self.temp.name) / "Long.pdf"
        writer = PdfWriter()
        for _ in range(18):
            writer.add_blank_page(width=600, height=800)
        writer.write(path)
        self.documents = [{**self.documents[0], "path": path, "page_count": 18,
            "notes": [f"Note page {index + 1}" for index in range(18)], "comments": []}]
        self.cards = [{"term": f"Question {index}", "definition": "Détail complet " + "x" * 6000} for index in range(300)]
        self.result["proposals"][0]["page"] = 18
        result = await self.run_validation()
        uploads = [call for call in self.calls if "session=1" in str(call.url)]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0].content, path.read_bytes())
        self.assertEqual(len(PdfReader(io.BytesIO(uploads[0].content)).pages), 18)
        context = json.loads(self.payloads["generate"][0]["contents"][0]["parts"][0]["text"])
        self.assertEqual(context["cards"], self.cards)
        self.assertEqual(context["documents"][0]["annotations"][-1]["notes"], "Note page 18")
        self.assertEqual(result["checked_cards"], 300)
        self.assertEqual(len(self.payloads["generate"]), 1)
        self.assert_cleaned()

    async def test_completed_empty_response_means_no_missing_information(self):
        self.result["proposals"] = []
        self.assertTrue((await self.run_validation())["covered"])
        self.assertEqual(len(self.payloads["generate"]), 1)
        self.assert_cleaned()

    async def test_incomplete_empty_response_never_claims_coverage(self):
        self.result.update(analysis_complete=False, proposals=[])
        with self.assertRaises(DeckError) as caught:
            await self.run_validation()
        self.assertEqual(caught.exception.status, 422)
        self.assert_cleaned()

    async def test_size_token_limit_rejects_before_generation_and_cleans_uploads(self):
        self.count = MAX_INPUT_TOKENS + 1
        with self.assertRaises(DeckError) as caught:
            await self.run_validation()
        self.assertEqual(caught.exception.status, 413)
        self.assertEqual(str(caught.exception), PROJECT_TOO_LARGE)
        self.assertNotIn("generate", self.payloads)
        self.assert_cleaned()

    async def test_exact_token_limit_is_accepted_and_reserved_without_estimation(self):
        self.count = MAX_INPUT_TOKENS
        await self.run_validation()
        self.assertEqual(self.coordinator.starts[-1][1], MAX_INPUT_TOKENS)
        self.assertEqual(self.coordinator.starts[0][1], 0)
        self.assert_cleaned()

    async def test_lower_configured_token_quota_is_respected(self):
        self.coordinator.tpm = 50
        with self.assertRaises(DeckError) as caught:
            await self.run_validation()
        self.assertEqual(str(caught.exception), PROJECT_TOO_LARGE)
        self.assertNotIn("generate", self.payloads)
        self.assert_cleaned()

    async def test_invalid_token_count_stops_before_generation(self):
        for count in (None, True, -1, 0, "100"):
            self.count = count
            self.calls = []; self.payloads = {}
            with self.assertRaises(DeckError) as caught:
                await self.run_validation()
            self.assertEqual(caught.exception.status, 502)
            self.assertNotIn("generate", self.payloads)
            self.assert_cleaned()

    async def test_too_many_cards_documents_or_pages_fail_before_external_calls(self):
        original_cards, original_documents = self.cards, self.documents
        for kind in ("cards", "documents", "pages"):
            self.cards = original_cards * 301 if kind == "cards" else original_cards
            self.documents = original_documents * 11 if kind == "documents" else copy.deepcopy(original_documents)
            if kind == "pages":
                self.documents[0]["page_count"] = 1000
            with self.assertRaises(DeckError) as caught:
                await self.run_validation()
            self.assertEqual(str(caught.exception), PROJECT_TOO_LARGE)
            self.assertEqual(self.calls, [])

    async def test_oversized_pdf_is_rejected_before_upload(self):
        with self.documents[0]["path"].open("wb") as source:
            source.truncate(MAX_PDF_BYTES + 1)
        with self.assertRaises(DeckError) as caught:
            await self.run_validation()
        self.assertEqual(str(caught.exception), PROJECT_TOO_LARGE)
        self.assertEqual(self.calls, [])

    async def test_annotation_alignment_and_actual_page_count_are_checked_before_upload(self):
        for changes in ({"page_count": 4}, {"notes": ["Une seule note"]}, {"comments": [[]]}):
            original = self.documents[0]
            self.documents[0] = {**original, **changes}
            with self.assertRaises(DeckError):
                await self.run_validation()
            self.assertEqual(self.calls, [])
            self.documents[0] = original

    async def test_output_too_large_is_reported_without_division_or_followup(self):
        for finish, too_large in (("MAX_TOKENS", False), ("STOP", True)):
            self.finish = finish
            self.result["project_too_large"] = too_large
            self.calls = []; self.payloads = {}
            with self.assertRaises(DeckError) as caught:
                await self.run_validation()
            self.assertEqual(str(caught.exception), PROJECT_TOO_LARGE)
            self.assertEqual(len(self.payloads["generate"]), 1)
            self.assert_cleaned()

    async def test_invalid_source_blank_details_and_duplicates_do_not_claim_coverage(self):
        bad = [{**PROPOSAL, "document_id": "unknown"}, {**PROPOSAL, "page": 4},
            {**PROPOSAL, "evidence": " "}, {**PROPOSAL, "missing_information": " "},
            {**PROPOSAL, **CARDS[0]}]
        for proposal in bad:
            self.result["proposals"] = [proposal]
            self.calls = []; self.payloads = {}
            with self.assertRaises(DeckError):
                await self.run_validation()
            self.assertEqual(len(self.payloads["generate"]), 1)
            self.assert_cleaned()
        self.result["proposals"] = [PROPOSAL, PROPOSAL]
        with self.assertRaises(DeckError):
            await self.run_validation()

    async def test_quota_and_provider_failures_cleanup_at_count_and_generation(self):
        for stage in ("count", "generate"):
            for status, expected in ((429, 429), (403, 503), (500, 502)):
                self.calls = []; self.payloads = {}; self.error_status = status; self.error_stage = stage
                with self.assertRaises(DeckError) as caught:
                    await self.run_validation()
                self.assertEqual(caught.exception.status, expected)
                self.assert_cleaned()

    async def test_processing_pdf_is_ready_before_count_and_analysis(self):
        self.processing = True
        await self.run_validation()
        self.assertEqual(sum(call.method == "GET" for call in self.calls), 2)
        self.assert_cleaned()

    async def test_polling_quota_is_preserved_and_uploaded_files_are_cleaned(self):
        self.processing = True; self.poll_status = 429
        with self.assertRaises(DeckError) as caught:
            await self.run_validation()
        self.assertEqual(caught.exception.status, 429)
        self.assert_cleaned()

    async def test_untrusted_upload_location_never_receives_key_or_document(self):
        for target in ("https://untrusted.test/upload", "http://generativelanguage.googleapis.com/upload",
                "https://generativelanguage.googleapis.com:bad/upload"):
            self.calls = []; self.upload_target = target
            with self.assertRaises(DeckError):
                await self.run_validation()
            self.assertTrue(all(str(call.url) == UPLOAD_URL for call in self.calls))

    async def test_identical_validation_reuses_completed_result_without_network(self):
        self.cache_directory = Path(self.temp.name) / "cache"
        first = await self.run_validation()
        self.calls = []; self.payloads = {}
        self.assertEqual(await self.run_validation(), first)
        self.assertEqual(self.calls, [])
        checkpoints = list(self.cache_directory.glob("*.json"))
        self.assertEqual(len(checkpoints), 1)
        content = checkpoints[0].read_text()
        self.assertNotIn("test-secret", content)
        self.assertNotIn(FILE_ROOT, content)
        self.assertEqual(checkpoints[0].stat().st_mode & 0o777, 0o600)

    async def test_changed_cards_notes_comments_or_pdf_invalidate_result(self):
        self.cache_directory = Path(self.temp.name) / "cache"
        await self.run_validation()
        for kind in ("cards", "notes", "comments", "pdf"):
            if kind == "cards":
                self.cards[0]["definition"] = "Autre réponse"
            elif kind == "notes":
                self.documents[0]["notes"][1] = "Note mise à jour"
            elif kind == "comments":
                self.documents[0]["comments"][1] = [{"text": "Autre commentaire"}]
            else:
                writer = PdfWriter()
                for _ in range(3):
                    writer.add_blank_page(width=601, height=800)
                writer.write(self.documents[0]["path"])
            self.calls = []; self.payloads = {}
            await self.run_validation()
            self.assertEqual(len(self.payloads["generate"]), 1)
            self.assert_cleaned()

    async def test_invalid_or_expired_cached_result_is_recomputed(self):
        self.cache_directory = Path(self.temp.name) / "cache"
        first = await self.run_validation()
        for expired in (False, True):
            checkpoint = next(self.cache_directory.glob("*.json"))
            if expired:
                stamp = time.time() - 31 * 86400
                os.utime(checkpoint, (stamp, stamp))
            else:
                value = json.loads(checkpoint.read_text())
                value["proposals"][0]["page"] = 999
                checkpoint.write_text(json.dumps(value))
            self.calls = []; self.payloads = {}
            self.assertEqual(await self.run_validation(), first)
            self.assertEqual(len(self.payloads["generate"]), 1)
            self.assert_cleaned()

    async def test_failed_generation_is_not_cached(self):
        self.cache_directory = Path(self.temp.name) / "cache"
        self.result["analysis_complete"] = False
        with self.assertRaises(DeckError):
            await self.run_validation()
        self.assertEqual(list(self.cache_directory.glob("*.json")), [])
        self.assert_cleaned()


class ValidationAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        accounts = Accounts(directory)
        owner = accounts.create("owner", "Owner", "validation-password-123", must_change=False)
        accounts.create("other", "Other", "validation-password-123", must_change=False)
        self.repository = MongoDecks(mongomock.MongoClient().memo.sets)
        self.document = ReferenceDocuments(directory).create(owner, course_pdf(directory / "Cours.pdf"), "Cours.pdf")
        self.client = TestClient(create_app(auth_enabled=True, require_https=True,
            data_dir=directory, deck_repository=self.repository), base_url="https://memo.test").__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.headers = {"Origin": "https://memo.test", "X-Memo-Request": "1"}
        self.login("owner")

    def login(self, name):
        self.client.post("/api/auth/login", json={"username": name, "password": "validation-password-123"}, headers=self.headers)

    def validate(self, **changes):
        return self.client.post("/api/sets/validate/coverage", json={"cards": CARDS,
            "document_ids": [self.document["id"]], **changes}, headers=self.headers)

    def test_unsaved_draft_validation_does_not_save_any_set(self):
        with patch("backend.main.validate_coverage", new_callable=AsyncMock, return_value={"covered": True, "proposals": []}) as service:
            result = self.validate()
            self.assertEqual(result.status_code, 200, result.text)
            self.assertTrue(result.json()["covered"])
            args = service.call_args.args
            self.assertEqual(args[0], CARDS)
            self.assertTrue(args[1][0]["path"].is_file())
            self.assertEqual(self.repository.collection.count_documents({}), 0)

    def test_unauthorized_duplicate_empty_and_partial_drafts_do_not_send(self):
        with patch("backend.main.validate_coverage", new_callable=AsyncMock) as service:
            for changes in [{"cards": [{"term": "Question", "definition": " "}]},
                    {"document_ids": []}, {"document_ids": [self.document["id"], self.document["id"]]}]:
                self.assertGreaterEqual(self.validate(**changes).status_code, 400)
            self.login("other")
            self.assertEqual(self.validate().status_code, 404)
            service.assert_not_called()

    def test_csrf_and_login_are_required(self):
        self.assertEqual(self.client.post("/api/sets/validate/coverage", json={"cards": CARDS,
            "document_ids": [self.document["id"]]}).status_code, 403)
        self.client.cookies.clear()
        self.assertEqual(self.validate().status_code, 401)

    def test_oversized_validation_requests_return_project_size_message(self):
        with patch("backend.main.validate_coverage", new_callable=AsyncMock) as service:
            for route in ("/api/sets/validate/coverage", "/api/validation-jobs"):
                for changes in ({"cards": CARDS * 301}, {"document_ids": [self.document["id"]] * 21}):
                    payload = {"cards": CARDS, "document_ids": [self.document["id"]], **changes}
                    if route == "/api/validation-jobs":
                        payload["draft_id"] = "oversized-draft"
                    response = self.client.post(route, json=payload, headers=self.headers)
                    self.assertEqual(response.status_code, 413, response.text)
                    self.assertEqual(response.json()["detail"], PROJECT_TOO_LARGE)
            service.assert_not_called()

    def test_closing_the_request_cancels_validation_and_releases_the_slot(self):
        import asyncio
        from threading import Event
        cancelled = Event()
        async def slow_validation(*args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        with patch("backend.main.validate_coverage", side_effect=slow_validation), patch(
                "backend.main.Request.is_disconnected", new_callable=AsyncMock, return_value=True):
            result = self.validate()
        self.assertEqual(result.status_code, 499)
        self.assertTrue(cancelled.is_set())


if __name__ == "__main__":
    unittest.main()
