import asyncio
import os
import unittest
from unittest.mock import patch

import httpx

from backend.decks import DeckError
from backend.gemini_requests import GeminiRequests, quota_details, quota_error


class FakeClock:
    def __init__(self):
        self.value = 0
        self.delays = []

    def now(self):
        return self.value

    async def sleep(self, delay):
        self.delays.append(delay)
        self.value += delay
        await asyncio.sleep(0)


def exhausted(identifier="GenerateRequestsPerMinutePerProjectPerModel-FreeTier", delay="2s", value="5"):
    details = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
        {"quotaId": identifier, "quotaValue": value, "quotaMetric": "requests"}]}]
    if delay:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay})
    return httpx.Response(429, json={"error": {"message": "private-provider-message", "details": details}})


class GeminiRequestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.payload = {"contents": [{"parts": [{"text": "Check a fact."}]}]}

    def coordinator(self, **values):
        return GeminiRequests(now=self.clock.now, sleep=self.clock.sleep, **values)

    def test_defaults_match_configured_project_quota_and_environment_can_override(self):
        with patch.dict(os.environ, {}, clear=True):
            coordinator = self.coordinator()
            self.assertEqual((coordinator.rpm, coordinator.tpm), (10, 250000))
        with patch.dict(os.environ, {"MEMO_GEMINI_RPM": "3", "MEMO_GEMINI_TPM": "50000"}):
            coordinator = self.coordinator()
            self.assertEqual((coordinator.rpm, coordinator.tpm), (3, 50000))

    async def test_measured_tokens_control_budget_instead_of_file_estimate(self):
        coordinator = self.coordinator(rpm=0, tpm=100)
        payload = {"contents": [{"parts": [{"fileData": {"mimeType": "application/pdf", "fileUri": "files/example"}}]}]}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))) as client:
            await coordinator.post(client, "https://example.test/generate", headers={}, json=payload, input_tokens=60)
        self.assertEqual(coordinator.starts[-1][1], 60)

    async def test_concurrent_validations_share_request_pacing(self):
        coordinator = self.coordinator(rpm=5, tpm=0)
        starts = []
        async def request():
            reservation = await coordinator.reserve(10)
            starts.append(reservation[0])
        await asyncio.gather(*(request() for _ in range(4)))
        self.assertEqual(len(starts), 4)
        self.assertTrue(all(right - left >= 12 for left, right in zip(starts, starts[1:])))

    async def test_token_budget_waits_until_previous_window_expires(self):
        coordinator = self.coordinator(rpm=0, tpm=100)
        first = await coordinator.reserve(60)
        second = await coordinator.reserve(60)
        self.assertGreaterEqual(second[0] - first[0], 60)
        with self.assertRaises(DeckError):
            await coordinator.reserve(101)

    async def test_temporary_quota_retries_only_after_provider_delay(self):
        responses = [exhausted(delay="7.5s"), httpx.Response(200, json={"usageMetadata": {"promptTokenCount": 3}})]
        starts = []
        def handle(request):
            starts.append(self.clock.now())
            return responses.pop(0)
        coordinator = self.coordinator(rpm=0, tpm=0)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            response = await coordinator.post(client, "https://example.test/generate", headers={}, json=self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(starts[1] - starts[0], 7.5)
        self.assertEqual(coordinator.starts[-1][1], 3)

    async def test_daily_and_unavailable_quotas_are_not_retried(self):
        for response in [exhausted(identifier="GenerateRequestsPerDayPerProjectPerModel-FreeTier"),
                exhausted(value="0")]:
            calls = []
            def handle(request):
                calls.append(request)
                return response
            coordinator = self.coordinator(rpm=0, tpm=0)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
                with self.assertRaises(DeckError) as caught:
                    await coordinator.post(client, "https://example.test/generate", headers={}, json=self.payload)
            self.assertEqual(len(calls), 1)
            self.assertNotIn("private-provider-message", str(caught.exception))

    async def test_unknown_quota_without_retry_info_is_not_blindly_retried(self):
        calls = []
        def handle(request):
            calls.append(request)
            return httpx.Response(429, json={"error": {"message": "secret"}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with self.assertRaises(DeckError):
                await self.coordinator(rpm=0, tpm=0).post(client, "https://example.test/generate", headers={}, json=self.payload)
        self.assertEqual(len(calls), 1)

    async def test_temporary_retries_are_bounded(self):
        calls = []
        def handle(request):
            calls.append(request)
            return exhausted()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with self.assertRaises(DeckError) as caught:
                await self.coordinator(rpm=0, tpm=0, retry_limit=2).post(client,
                    "https://example.test/generate", headers={}, json=self.payload)
        self.assertEqual(len(calls), 3)
        self.assertIn("par minute", str(caught.exception))

    def test_daily_quota_takes_precedence_over_minute_quota(self):
        response = exhausted()
        data = response.json()
        data["error"]["details"][0]["violations"].append({"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"})
        daily = httpx.Response(429, json=data)
        self.assertEqual(quota_details(daily)[0], "daily")
        self.assertIn("quotidien", str(quota_error(daily)))

    def test_malformed_quota_error_stays_safe(self):
        for response in [httpx.Response(429, text="invalid JSON"), httpx.Response(429, json={"error": None})]:
            self.assertEqual(quota_details(response), ("unknown", None))
            self.assertEqual(quota_error(response).status, 429)
