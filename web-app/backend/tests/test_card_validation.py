import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import mongomock
from pypdf import PdfReader, PdfWriter
from fastapi.testclient import TestClient

from backend.auth import Accounts
from backend.card_validation import FILE_ROOT, GEMINI_URL, UPLOAD_URL, validate_coverage
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
        self.cards = CARDS
        self.calls, self.contexts = [], []
        self.facts = {("doc1", 2): [{"information": "Information manquante.", "evidence": "Notes de la deuxième slide."}]}
        self.error_status = None
        self.error_stage = None
        self.finish = "STOP"
        self.processing = False
        self.poll_status = None
        self.upload_target = UPLOAD_URL + "?session=1"
        self.inventory_transform = lambda result: result
        self.match_transform = lambda result: result
        self.author_transform = lambda result: result
        self.match_fact = lambda fact, cards: {"fact_index": fact["fact_index"], "status": "missing",
            "card_evidence": [], "reason": "Information absente des cartes de ce groupe."}

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
                return httpx.Response(200, json={"name": request.url.path.rsplit('/', 1)[-1],
                    "uri": str(request.url), "state": "ACTIVE"})
            self.assertEqual(str(request.url), GEMINI_URL)
            body = json.loads(request.content)
            parts = body["contents"][0]["parts"]
            context = json.loads(parts[0]["text"])
            self.contexts.append(context)
            if self.error_status and (self.error_stage is None or self.error_stage == "match" and "facts" in context):
                return httpx.Response(self.error_status)
            if "original_pages" in context:
                self.assertEqual(sum("fileData" in part for part in parts), 1)
                self.assertNotIn("cards", context)
                result = {"analysis_complete": True, "pages": [{"page": page,
                    "has_information": bool(self.facts.get((context["id"], page))),
                    "facts": self.facts.get((context["id"], page), [])} for page in context["original_pages"]]}
                result = self.inventory_transform(result)
            elif "facts" in context:
                self.assertFalse(any("fileData" in part for part in parts))
                result = self.match_transform({"analysis_complete": True,
                    "matches": [self.match_fact(fact, context["cards"]) for fact in context["facts"]]})
            else:
                result = self.author_transform({"analysis_complete": True, "proposals": [
                    {"term": "Question sur " + fact["information"], "definition": fact["information"],
                        "fact_indices": [index]} for index, fact in enumerate(context["missing_facts"])]})
            return generated(result, self.finish)
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with patch("backend.card_validation.api_key", return_value="test-secret"), patch("backend.card_validation.httpx.AsyncClient", return_value=client):
            return await validate_coverage(self.cards, self.documents,
                requests=GeminiRequests(rpm=0, tpm=0, retry_limit=0),
                cache_directory=getattr(self, "cache_directory", None))

    def assert_cleaned(self):
        uploaded = sum("session=1" in str(call.url) for call in self.calls)
        deleted = [str(call.url) for call in self.calls if call.method == "DELETE"]
        self.assertEqual(len(set(deleted)), uploaded)
        self.assertEqual(len(deleted), uploaded)

    async def test_all_pdf_pages_notes_and_comments_are_inventoried_before_matching(self):
        result = await self.run_validation()
        self.assertFalse(result["covered"])
        self.assertEqual(len(result["proposals"]), 1)
        proposal = result["proposals"][0]
        self.assertEqual(proposal["document_id"], "doc1")
        self.assertEqual(proposal["page"], 2)
        self.assertEqual(proposal["definition"], "Information manquante.")
        inventories = [context for context in self.contexts if "original_pages" in context]
        self.assertEqual(len(inventories), 2)
        source = next(context for context in inventories if context["id"] == "doc1")
        self.assertEqual(source["annotations"][1]["notes"], "Notes de la deuxième slide.")
        self.assertEqual(source["annotations"][1]["comments"][0]["text"], "Précision du professeur.")
        self.assertEqual(result["checked_pages"], 6)
        self.assert_cleaned()

    async def test_many_documents_and_cards_find_fact_in_last_document(self):
        self.documents = [{**self.documents[1], "id": f"doc{index}"} for index in range(20)]
        self.cards = [{"term": f"Question {index}", "definition": f"Réponse existante {index}"} for index in range(300)]
        self.facts = {("doc19", 3): [{"information": "Une information entièrement nouvelle du document de support.", "evidence": "Une information entièrement nouvelle."}]}
        result = await self.run_validation()
        self.assertFalse(result["covered"])
        self.assertEqual(result["proposals"][0]["document_id"], "doc19")
        inventories = [context for context in self.contexts if "original_pages" in context]
        self.assertEqual({context["id"] for context in inventories}, {document["id"] for document in self.documents})
        matches = [context for context in self.contexts if "facts" in context]
        self.assertEqual({card["card_index"] for context in matches for card in context["cards"]}, set(range(300)))
        self.assertTrue(all(len(context["cards"]) <= 60 for context in matches))
        self.assertEqual(result["checked_cards"], 300)
        self.assert_cleaned()

    async def test_long_pdf_keeps_original_page_numbers_and_note_alignment(self):
        path = Path(self.temp.name) / "Long.pdf"
        writer = PdfWriter()
        for _ in range(18):
            writer.add_blank_page(width=600, height=800)
        writer.write(path)
        self.documents = [{**self.documents[0], "path": path, "page_count": 18,
            "notes": [f"Note page {index + 1}" for index in range(18)], "comments": []}]
        self.facts = {("doc1", 18): [{"information": "Dernière information.", "evidence": "Note page 18"}]}
        result = await self.run_validation()
        inventories = sorted((context for context in self.contexts if "original_pages" in context), key=lambda context: context["original_pages"][0])
        self.assertEqual([context["original_pages"] for context in inventories], [list(range(1, 9)), list(range(9, 17)), [17, 18]])
        self.assertEqual(inventories[-1]["annotations"][-1]["notes"], "Note page 18")
        self.assertEqual(result["proposals"][0]["page"], 18)
        sizes = [len(PdfReader(io.BytesIO(call.content)).pages) for call in self.calls if "session=1" in str(call.url)]
        self.assertEqual(sizes, [8, 8, 2])
        self.assert_cleaned()

    async def test_fact_covered_in_last_card_batch_does_not_get_proposed(self):
        self.cards = [{"term": f"Question {index}", "definition": f"Réponse {index}"} for index in range(300)]
        self.cards[-1]["definition"] = "Information manquante."
        def match(fact, cards):
            existing = next((card for card in cards if card["definition"] == fact["information"]), None)
            return {"fact_index": fact["fact_index"], "status": "covered" if existing else "missing",
                "card_evidence": [{"card_index": existing["card_index"], "quote": existing["definition"]}] if existing else [], "reason": "Comparaison explicite."}
        self.match_fact = match
        result = await self.run_validation()
        self.assertTrue(result["covered"])
        self.assertEqual(result["proposals"], [])
        self.assertFalse(any("missing_facts" in context for context in self.contexts))

    async def test_partial_coverage_split_across_card_batches_is_reconciled(self):
        self.cards = [{"term": f"Question {index}", "definition": f"Autre réponse {index}"} for index in range(61)]
        self.cards[0]["definition"] = "Première moitié."
        self.cards[60]["definition"] = "Seconde moitié."
        def match(fact, cards):
            relevant = [card for card in cards if card["card_index"] in (0, 60)]
            return {"fact_index": fact["fact_index"], "status": "covered" if len(relevant) == 2 else "partial" if relevant else "missing",
                "card_evidence": [{"card_index": card["card_index"], "quote": card["definition"]} for card in relevant], "reason": "Couverture répartie sur deux cartes."}
        self.match_fact = match
        self.assertTrue((await self.run_validation())["covered"])
        reconciled = [context for context in self.contexts if "facts" in context and len(context["cards"]) == 2]
        self.assertEqual(len(reconciled), 1)

    async def test_large_card_text_is_batched_without_truncation(self):
        self.cards = [{"term": f"Question {index}", "definition": f"Détail {index} " + "x" * 6000} for index in range(30)]
        await self.run_validation()
        matches = [context for context in self.contexts if "facts" in context]
        supplied = {card["card_index"]: card["definition"] for context in matches for card in context["cards"]}
        self.assertEqual(supplied, {index: card["definition"] for index, card in enumerate(self.cards)})
        self.assertTrue(all(len(json.dumps(context["cards"], ensure_ascii=False)) < 61000 for context in matches))

    async def test_empty_authoring_for_missing_information_never_claims_coverage(self):
        self.author_transform = lambda result: {**result, "proposals": []}
        with self.assertRaises(DeckError) as caught:
            await self.run_validation()
        self.assertEqual(caught.exception.status, 422)
        self.assert_cleaned()

    async def test_omitted_page_incomplete_page_and_truncation_never_claim_coverage(self):
        for transform in [lambda result: {**result, "pages": result["pages"][:-1]},
                lambda result: {**result, "analysis_complete": False},
                lambda result: {**result, "pages": [{"page": page["page"], "has_information": True, "facts": []} for page in result["pages"]]}]:
            self.calls = []; self.inventory_transform = transform
            with self.assertRaises(DeckError):
                await self.run_validation()
            self.assert_cleaned()
        self.calls = []; self.inventory_transform = lambda result: result; self.finish = "MAX_TOKENS"
        with self.assertRaises(DeckError):
            await self.run_validation()
        self.assert_cleaned()

    async def test_every_fact_requires_a_match_and_coverage_requires_real_card_quotes(self):
        bad = [{"analysis_complete": True, "matches": []},
            {"analysis_complete": True, "matches": [{"fact_index": 0, "status": "covered",
                "card_evidence": [], "reason": "Assumption"}]},
            {"analysis_complete": True, "matches": [{"fact_index": 0, "status": "covered",
                "card_evidence": [{"card_index": 0, "quote": "Invented quotation"}], "reason": "Assumption"}]},
            {"analysis_complete": True, "matches": [{"fact_index": 0, "status": "covered",
                "card_evidence": [{"card_index": 99, "quote": "Réponse déjà couverte."}], "reason": "Assumption"}]}]
        for result in bad:
            self.calls = []; self.match_transform = lambda original: result
            with self.assertRaises(DeckError):
                await self.run_validation()
            self.assert_cleaned()

    async def test_empty_extraction_cannot_confirm_coverage(self):
        self.facts = {}
        with self.assertRaises(DeckError) as caught:
            await self.run_validation()
        self.assertEqual(caught.exception.status, 422)
        self.assert_cleaned()

    async def test_quota_and_provider_failures_cleanup(self):
        for status, expected in [(429, 429), (403, 503), (500, 502)]:
            self.calls = []; self.error_status = status
            with self.assertRaises(DeckError) as caught:
                await self.run_validation()
            self.assertEqual(caught.exception.status, expected)
            self.assert_cleaned()

    async def test_page_limit_fails_before_any_external_call(self):
        self.documents[0]["page_count"] = 1000
        with self.assertRaises(DeckError) as caught:
            await self.run_validation()
        self.assertEqual(caught.exception.status, 413)
        self.assertEqual(self.calls, [])

    async def test_processing_pdf_is_ready_before_analysis(self):
        self.processing = True
        self.assertFalse((await self.run_validation())["covered"])
        self.assertEqual(sum(call.method == "GET" for call in self.calls), 2)
        self.assert_cleaned()

    async def test_polling_quota_is_preserved_and_uploaded_files_are_cleaned(self):
        self.processing = True; self.poll_status = 429
        with self.assertRaises(DeckError) as caught:
            await self.run_validation()
        self.assertEqual(caught.exception.status, 429)
        self.assert_cleaned()

    async def test_untrusted_upload_location_never_receives_key_or_document(self):
        for target in ["https://untrusted.test/upload", "http://generativelanguage.googleapis.com/upload", "https://generativelanguage.googleapis.com:bad/upload"]:
            self.calls = []; self.upload_target = target
            with self.assertRaises(DeckError):
                await self.run_validation()
            self.assertTrue(all(str(call.url) == UPLOAD_URL for call in self.calls))

    async def test_identical_validation_reuses_all_completed_steps_without_network(self):
        self.cache_directory = Path(self.temp.name) / "cache"
        first = await self.run_validation()
        self.calls = []; self.contexts = []
        second = await self.run_validation()
        self.assertEqual(first, second)
        self.assertEqual(self.calls, [])
        for checkpoint in self.cache_directory.glob("*.json"):
            content = checkpoint.read_text()
            self.assertNotIn("test-secret", content)
            self.assertNotIn(FILE_ROOT, content)
            self.assertEqual(checkpoint.stat().st_mode & 0o777, 0o600)

    async def test_card_changes_reuse_source_extraction_but_recheck_cards(self):
        self.cache_directory = Path(self.temp.name) / "cache"
        await self.run_validation()
        self.cards = [{"term": "Nouvelle question", "definition": "Nouvelle réponse"}]
        self.calls = []; self.contexts = []
        await self.run_validation()
        self.assertTrue(self.calls)
        self.assertTrue(all(str(call.url) == GEMINI_URL for call in self.calls))
        self.assertTrue(any("facts" in context for context in self.contexts))
        self.assertFalse(any("original_pages" in context for context in self.contexts))

    async def test_changed_notes_invalidate_only_the_affected_document_inventory(self):
        self.cache_directory = Path(self.temp.name) / "cache"
        await self.run_validation()
        self.documents[0]["notes"][1] = "Notes mises à jour."
        self.facts[("doc1", 2)] = [{"information": "Nouvelle information.", "evidence": "Notes mises à jour."}]
        self.calls = []; self.contexts = []
        result = await self.run_validation()
        inventories = [context for context in self.contexts if "original_pages" in context]
        self.assertEqual([context["id"] for context in inventories], ["doc1"])
        self.assertEqual(result["proposals"][0]["definition"], "Nouvelle information.")

    async def test_quota_failure_keeps_completed_inventories_for_retry(self):
        self.cache_directory = Path(self.temp.name) / "cache"
        self.error_stage = "match"; self.error_status = 429
        with self.assertRaises(DeckError):
            await self.run_validation()
        self.error_status = None; self.calls = []; self.contexts = []
        result = await self.run_validation()
        self.assertFalse(result["covered"])
        self.assertTrue(all(str(call.url) == GEMINI_URL for call in self.calls))
        self.assertFalse(any("original_pages" in context for context in self.contexts))

    async def test_pdf_content_change_invalidates_inventory(self):
        self.cache_directory = Path(self.temp.name) / "cache"
        await self.run_validation()
        writer = PdfWriter()
        for _ in range(3):
            writer.add_blank_page(width=601, height=800)
        writer.write(self.documents[0]["path"])
        self.calls = []; self.contexts = []
        await self.run_validation()
        self.assertEqual(sum("original_pages" in context for context in self.contexts), 2)

    async def test_cached_coverage_is_still_checked_against_real_card_text(self):
        self.cache_directory = Path(self.temp.name) / "cache"
        first = await self.run_validation()
        for checkpoint in self.cache_directory.glob("*.json"):
            value = json.loads(checkpoint.read_text())
            if "matches" in value:
                value["matches"][0].update(status="covered", card_evidence=[{"card_index": 0, "quote": "Invented quotation"}])
                checkpoint.write_text(json.dumps(value))
        self.calls = []; self.contexts = []
        second = await self.run_validation()
        self.assertEqual(first, second)
        self.assertEqual(sum("facts" in context for context in self.contexts), 1)

    async def test_expired_cache_is_recomputed(self):
        import os
        import time
        self.cache_directory = Path(self.temp.name) / "cache"
        first = await self.run_validation()
        expired = time.time() - 31 * 86400
        for checkpoint in self.cache_directory.glob("*.json"):
            os.utime(checkpoint, (expired, expired))
        self.calls = []; self.contexts = []
        second = await self.run_validation()
        self.assertEqual(first, second)
        self.assertEqual(sum("original_pages" in context for context in self.contexts), 2)



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
