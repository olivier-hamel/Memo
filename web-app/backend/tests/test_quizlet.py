"""Quizlet import boundary tests; external pages and Gemini are mocked."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import mongomock
from fastapi.testclient import TestClient

from backend.auth import Accounts
from backend.decks import DeckError, MongoDecks
from backend.main import create_app
from backend.quizlet import GEMINI_URL, PageContent, api_key, extract_set, fetch_page, import_quizlet, quizlet_url

URL = "https://quizlet.com/fr/123456/bonjour-flash-cards/"
CARDS = [{"term": "Bonjour", "definition": "Hello"}, {"term": "Merci", "definition": "Thank you\nThanks"}]
RESULT = {"title": "Salutations", "description": "Français & anglais", "complete": True, "expected_count": 2, "cards": CARDS}
PAGE = """<!doctype html><html><head><title>Salutations | Quizlet</title>
<style>discard-styles</style><script src="/bundle.js">discard-bundle</script></head>
<body><main><h1>Salutations</h1><h2>Terms in this set (2)</h2>
<div class="SetPageTerm" data-testid="set-term"><span class="TermText">Bonjour</span><span>Hello</span></div>
<div class="SetPageTerm"><span>Merci</span><span>Thank you<br>Thanks</span></div></main>
<script id="__NEXT_DATA__" type="application/json">{"set":{"id":123456,"terms":[{"word":"Bonjour","definition":"Hello"}]}}</script>
<svg><text>discard-icon</text></svg></body></html>"""


def response_for(result=RESULT, finish="STOP"):
    return {"candidates": [{"finishReason": finish, "content": {"parts": [{"text": json.dumps(result)}]}}]}


class QuizletUrlTests(unittest.TestCase):
    def test_accepts_public_set_urls_and_removes_tracking(self):
        self.assertEqual(quizlet_url(URL + "?i=abc&x=1#cards"), URL)
        self.assertEqual(quizlet_url(" https://www.quizlet.com/123/test-flash-cards/ "), "https://www.quizlet.com/123/test-flash-cards/")
        self.assertEqual(quizlet_url("https://quizlet.com/123"), "https://quizlet.com/123")

    def test_rejects_other_hosts_credentials_ports_and_non_set_paths(self):
        for url in ["http://quizlet.com/123", "https://quizlet.com.evil.test/123", "https://evil.test/123",
                    "https://quizlet.com@127.0.0.1/123", "https://user@quizlet.com/123", "https://quizlet.com:444/123",
                    "https://quizlet.com/login", "https://quizlet.com/123/../login", "https://quizlet.com/123%2fadmin",
                    "https://quizlet.com\\@127.0.0.1/123", "https://quizlet.com:invalid/123", "file:///123"]:
            with self.subTest(url=url), self.assertRaises(DeckError):
                quizlet_url(url)

    def test_text_and_dom_keep_cards_and_embedded_data_but_not_assets(self):
        page = PageContent()
        page.feed(PAGE)
        snapshot = page.snapshot()
        self.assertIn("Bonjour", snapshot["text"])
        self.assertIn('class="SetPageTerm"', snapshot["dom"])
        self.assertIn('"word":"Bonjour"', snapshot["dom"])
        for value in ["discard-styles", "discard-bundle", "discard-icon"]:
            self.assertNotIn(value, snapshot["text"] + snapshot["dom"])

    def test_secret_loads_from_environment_or_private_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key"
            path.write_text("file-key\n")
            with patch.dict(os.environ, {"MEMO_GEMINI_API_KEY": "env-key", "MEMO_GEMINI_API_KEY_FILE": str(path)}):
                self.assertEqual(api_key(), "env-key")
                os.environ["MEMO_GEMINI_API_KEY"] = ""
                self.assertEqual(api_key(), "file-key")
                path.unlink()
                with self.assertRaises(DeckError) as error:
                    api_key()
                self.assertEqual(error.exception.status, 503)


class QuizletNetworkTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        transport = patch.dict(os.environ, {"MEMO_QUIZLET_BROWSER_HTTP": "0"})
        transport.start()
        self.addCleanup(transport.stop)

    async def test_fetch_then_gemini_extracts_full_set_with_text_and_dom(self):
        calls = []
        def handle(request):
            calls.append(request)
            if request.method == "GET":
                return httpx.Response(200, text=PAGE, headers={"content-type": "text/html; charset=utf-8"})
            self.assertEqual(str(request.url), GEMINI_URL)
            self.assertEqual(request.headers["x-goog-api-key"], "test-secret")
            self.assertNotIn("test-secret", str(request.url))
            body = json.loads(request.content)
            source = json.loads(body["contents"][0]["parts"][0]["text"])
            self.assertIn("Bonjour", source["text"])
            self.assertIn('class="SetPageTerm"', source["dom"])
            self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
            return httpx.Response(200, json=response_for())
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with patch("backend.quizlet.api_key", return_value="test-secret"), patch("backend.quizlet.httpx.AsyncClient", return_value=client):
            imported = await import_quizlet(URL)
        self.assertEqual(imported, {key: RESULT[key] for key in ["title", "description", "cards"]})
        self.assertEqual([request.method for request in calls], ["GET", "POST"])

    async def test_redirect_is_validated_before_contacting_another_host(self):
        calls = []
        def handle(request):
            calls.append(request)
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with self.assertRaises(DeckError):
                await fetch_page(client, URL)
        self.assertEqual(len(calls), 1)

    async def test_relative_quizlet_redirect_is_followed(self):
        calls = []
        def handle(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(301, headers={"location": "/123456/bonjour-flash-cards/"})
            return httpx.Response(200, text=PAGE, headers={"content-type": "text/html"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            source, _ = await fetch_page(client, URL)
        self.assertEqual(source, "https://quizlet.com/123456/bonjour-flash-cards/")

    async def test_private_blocked_non_html_and_oversized_pages_fail(self):
        for status, body, content_type in [(403, "Denied", "text/html"), (404, "Private", "text/html"),
                (200, "<h1>Just a moment...</h1>", "text/html"), (200, "{}", "application/json"),
                (200, "x" * 1024, "text/html")]:
            with self.subTest(status=status, content_type=content_type):
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(status, text=body, headers={"content-type": content_type}))) as client:
                    with patch("backend.quizlet.MAX_PAGE_BYTES", 512), self.assertRaises(DeckError):
                        await fetch_page(client, URL)

    async def test_rejects_partial_empty_invalid_duplicate_and_oversized_extractions(self):
        bad_results = [
            {**RESULT, "complete": False}, {**RESULT, "expected_count": 3},
            {**RESULT, "cards": []}, {**RESULT, "cards": [CARDS[0], CARDS[0]]},
            {**RESULT, "cards": [{"term": " ", "definition": "text"}, CARDS[1]]},
            {**RESULT, "cards": [{"term": "word", "definition": ""}, CARDS[1]]},
            {**RESULT, "expected_count": 301}, {**RESULT, "complete": "true"},
        ]
        for result in bad_results:
            with self.subTest(result=result):
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response_for(result)))) as client:
                    with self.assertRaises(DeckError):
                        await extract_set(client, "test-secret", URL, {"text": "", "dom": PAGE})

    async def test_provider_errors_and_truncated_output_are_safe(self):
        for status, body, expected_status in [(429, {"error": "secret provider data"}, 429),
                (403, {"error": "secret provider data"}, 503), (503, {"error": "secret provider data"}, 502),
                (200, response_for(finish="MAX_TOKENS"), 422), (200, {"promptFeedback": {"blockReason": "SAFETY"}}, 422),
                (200, {"candidates": [None]}, 422),
                (200, {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "not JSON"}]}}]}, 422)]:
            with self.subTest(status=status, body=body):
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body))) as client:
                    with self.assertRaises(DeckError) as error:
                        await extract_set(client, "test-secret", URL, {"text": "", "dom": PAGE})
                self.assertEqual(error.exception.status, expected_status)
                self.assertNotIn("secret", str(error.exception))

    async def test_model_cannot_invent_answers_or_ignore_advertised_card_count(self):
        page = PageContent()
        page.feed(PAGE)
        for result in [{**RESULT, "cards": [{**CARDS[0], "definition": "Invented answer"}, CARDS[1]]},
                       {**RESULT, "expected_count": 1, "cards": [CARDS[0]]}]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response_for(result)))) as client:
                with self.assertRaises(DeckError):
                    await extract_set(client, "test-secret", URL, page.snapshot())

    async def test_embedded_json_cards_preserve_unicode_quotes_and_line_breaks(self):
        cards = [{"term": 'Éthique "A"', "definition": "L’ingénieur\nDeuxième ligne"}]
        result = {**RESULT, "expected_count": 1, "cards": cards}
        page = PageContent()
        page.feed('<h1>Title</h1><script id="__NEXT_DATA__" type="application/json">' + json.dumps({"cards": cards}) + '</script>')
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response_for(result)))) as client:
            imported = await extract_set(client, "test-secret", URL, page.snapshot())
        self.assertEqual(imported["cards"], cards)

    async def test_later_cards_in_nested_serialized_quizlet_store_are_valid_sources(self):
        cards = [{"term": 'Éthique "A"', "definition": "L’ingénieur\nDeuxième ligne"}]
        result = {**RESULT, "expected_count": 1, "cards": cards}
        data = {"props": {"pageProps": {"dehydratedReduxStateKey": json.dumps({"setPage": {"terms": cards}})}}}
        page = PageContent()
        page.feed('<h1>Title</h1><script id="__NEXT_DATA__" type="application/json">' + json.dumps(data) + '</script>')
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response_for(result)))) as client:
            imported = await extract_set(client, "test-secret", URL, page.snapshot())
        self.assertEqual(imported["cards"], cards)

    async def test_timeout_returns_actionable_error(self):
        with patch("backend.quizlet.api_key", return_value="test-secret"), patch("backend.quizlet.fetch_page", side_effect=httpx.ReadTimeout("secret detail")):
            with self.assertRaises(DeckError) as error:
                await import_quizlet(URL)
        self.assertEqual(error.exception.status, 504)
        self.assertNotIn("secret", str(error.exception))


class QuizletEndpointTests(unittest.TestCase):
    def test_requires_account_and_csrf_then_returns_draft_without_saving(self):
        headers = {"Origin": "https://memo.test", "X-Memo-Request": "1"}
        with tempfile.TemporaryDirectory() as directory:
            Accounts(directory).create("importer", "Importer", "test-password-12345", must_change=False)
            repository = MongoDecks(mongomock.MongoClient().memo.sets)
            app = create_app(auth_enabled=True, require_https=True, data_dir=directory, deck_repository=repository)
            with TestClient(app, base_url="https://memo.test") as client, patch("backend.main.import_quizlet", new_callable=AsyncMock) as importer:
                importer.return_value = {key: RESULT[key] for key in ["title", "description", "cards"]}
                self.assertEqual(client.post("/api/sets/import/quizlet", json={"url": URL}, headers=headers).status_code, 401)
                client.post("/api/auth/login", json={"username": "importer", "password": "test-password-12345"}, headers=headers)
                self.assertEqual(client.post("/api/sets/import/quizlet", json={"url": URL}).status_code, 403)
                importer.assert_not_called()
                response = client.post("/api/sets/import/quizlet", json={"url": URL}, headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["cards"], CARDS)
                importer.assert_awaited_once_with(URL)
                self.assertEqual(repository.collection.count_documents({}), 0)
                self.assertEqual(client.post("/api/sets/import/quizlet", json={"url": URL, "key": "client-key"}, headers=headers).status_code, 422)

    def test_disabled_library_cannot_import(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(auth_enabled=False, progress_path=Path(directory) / "progress.json", legacy_path=None)
            with TestClient(app) as client, patch("backend.main.import_quizlet", new_callable=AsyncMock) as importer:
                self.assertEqual(client.post("/api/sets/import/quizlet", json={"url": URL}).status_code, 403)
                importer.assert_not_called()
