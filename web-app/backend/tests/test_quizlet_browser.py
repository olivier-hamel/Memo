"""Browser HTTPS transport tests using fixtures; no external requests."""
import json
import os
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

import httpx
from curl_cffi.requests.exceptions import Timeout

from backend.decks import DeckError
from backend.quizlet import GEMINI_URL, fetch_page, import_quizlet
from backend.quizlet_browser import BrowserPageClient
from backend.tests.test_quizlet import CARDS, PAGE, RESULT, URL, response_for


class FixtureResponse:
    def __init__(self, body=PAGE, status=200, headers=None):
        self.status_code = status
        self.headers = headers or {"content-type": "text/html; charset=utf-8"}
        self.encoding = "utf-8"
        self.body = body.encode()

    async def aiter_content(self):
        yield self.body


class FixtureSession:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    @asynccontextmanager
    async def stream(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        yield response


class BrowserTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_browser_fetch_fills_cards_with_gemini_without_sending_key_to_quizlet(self):
        session = FixtureSession([FixtureResponse()])
        def gemini(request):
            self.assertEqual(str(request.url), GEMINI_URL)
            self.assertEqual(request.headers["x-goog-api-key"], "server-key")
            source = json.loads(json.loads(request.content)["contents"][0]["parts"][0]["text"])
            self.assertIn("Bonjour", source["text"])
            return httpx.Response(200, json=response_for())
        client = httpx.AsyncClient(transport=httpx.MockTransport(gemini))
        with patch.dict(os.environ, {"MEMO_QUIZLET_BROWSER_HTTP": "1"}), \
                patch("backend.quizlet.api_key", return_value="server-key"), \
                patch("backend.quizlet.httpx.AsyncClient", return_value=client), \
                patch("backend.quizlet_browser.AsyncSession", return_value=session) as factory:
            result = await import_quizlet(URL)
        self.assertEqual(result["cards"], CARDS)
        factory.assert_called_once_with(impersonate="chrome", timeout=25, verify=True)
        self.assertEqual(len(session.requests), 1)
        method, url, options = session.requests[0]
        self.assertEqual((method, url), ("GET", URL))
        self.assertFalse(options["allow_redirects"])
        self.assertNotIn("User-Agent", options["headers"])
        self.assertNotIn("x-goog-api-key", options["headers"])

    async def test_browser_redirect_to_another_host_is_not_followed(self):
        session = FixtureSession([FixtureResponse(status=302, headers={"location": "https://example.com/123"})])
        with patch("backend.quizlet_browser.AsyncSession", return_value=session):
            async with BrowserPageClient() as client:
                with self.assertRaises(DeckError):
                    await fetch_page(client, URL)
        self.assertEqual(len(session.requests), 1)

    async def test_browser_block_and_oversize_preserve_existing_limits(self):
        for response, expected in [(FixtureResponse(status=403), 422), (FixtureResponse(body="x" * 600), 413)]:
            session = FixtureSession([response])
            with patch("backend.quizlet_browser.AsyncSession", return_value=session), patch("backend.quizlet.MAX_PAGE_BYTES", 512):
                async with BrowserPageClient() as client:
                    with self.assertRaises(DeckError) as error:
                        await fetch_page(client, URL)
            self.assertEqual(error.exception.status, expected)

    async def test_browser_timeout_becomes_safe_import_error(self):
        session = FixtureSession([Timeout("private upstream detail")])
        with patch.dict(os.environ, {"MEMO_QUIZLET_BROWSER_HTTP": "1"}), \
                patch("backend.quizlet.api_key", return_value="server-key"), \
                patch("backend.quizlet_browser.AsyncSession", return_value=session):
            with self.assertRaises(DeckError) as error:
                await import_quizlet(URL)
        self.assertEqual(error.exception.status, 504)
        self.assertNotIn("private", str(error.exception))
