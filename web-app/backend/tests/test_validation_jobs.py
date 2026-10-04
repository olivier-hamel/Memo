import asyncio
import json
import stat
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import AsyncMock, patch

from backend.decks import DeckError
from backend.gemini_requests import GeminiRequests
from backend.validation_jobs import ValidationJobs
from backend.tests.test_card_validation import CARDS
from backend.tests import test_card_validation as api_fixtures


class BackgroundValidationAPITests(unittest.TestCase):
    setUp = api_fixtures.ValidationAPITests.setUp
    login = api_fixtures.ValidationAPITests.login

    def start(self, **changes):
        return self.client.post('/api/validation-jobs', headers=self.headers, json={
            'title': 'Mon brouillon', 'description': 'À conserver', 'set_id': None, 'draft_id': 'draft-1',
            'cards': CARDS, 'document_ids': [self.document['id']], **changes})

    def wait_done(self, identifier):
        for _ in range(200):
            job = self.client.get('/api/validation-jobs/' + identifier).json()
            if job['status'] not in ('running', 'queued'):
                return job
            time.sleep(.01)
        self.fail('Background validation did not finish')

    def test_request_returns_immediately_and_job_continues_after_disconnect(self):
        started, release = Event(), Event()
        async def validate(cards, documents, **kwargs):
            started.set()
            kwargs['progress']('Lecture des documents · 1 / 3 pages')
            while not release.is_set():
                await asyncio.sleep(.01)
            return {'covered': True, 'proposals': [], 'checked_pages': 3, 'checked_cards': 1}
        with patch('backend.main.validate_coverage', side_effect=validate), patch(
                'backend.main.Request.is_disconnected', new_callable=AsyncMock, return_value=True):
            response = self.start()
            self.assertEqual(response.status_code, 202, response.text)
            identifier = response.json()['id']
            self.assertTrue(started.wait(1))
            job = self.client.get('/api/validation-jobs/' + identifier).json()
            self.assertEqual(job['status'], 'running')
            self.assertIn('1 / 3', job['progress'])
            self.assertEqual(job['snapshot']['cards'], CARDS)
            self.assertEqual(self.start().json()['id'], identifier)
            self.assertEqual(self.start(title='Different').status_code, 409)
            release.set()
            job = self.wait_done(identifier)
        self.assertEqual(job['status'], 'completed')
        self.assertTrue(job['unread'])
        self.assertEqual(self.repository.collection.count_documents({}), 0)
        listing = self.client.get('/api/validation-jobs').json()['jobs']
        self.assertNotIn('snapshot', listing[0])
        self.assertNotIn('result', listing[0])
        self.assertEqual(self.client.post(f'/api/validation-jobs/{identifier}/read', headers=self.headers, json={}).status_code, 200)
        self.assertFalse(self.client.get('/api/validation-jobs/' + identifier).json()['unread'])

    def test_ownership_csrf_and_documents_are_checked(self):
        with patch('backend.main.validate_coverage', new_callable=AsyncMock) as service:
            self.assertEqual(self.start(document_ids=[]).status_code, 422)
            self.assertEqual(self.start(document_ids=['missing']).status_code, 404)
            self.login('other')
            self.assertEqual(self.start().status_code, 404)
            self.assertEqual(self.client.get('/api/validation-jobs').json()['jobs'], [])
            service.assert_not_called()
        self.assertEqual(self.client.post('/api/validation-jobs', json={}).status_code, 403)
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/validation-jobs').status_code, 401)

    def test_failed_jobs_are_visible_and_private_results_survive_restart(self):
        with patch('backend.main.validate_coverage', new_callable=AsyncMock, side_effect=DeckError(429, 'Quota minute atteint')):
            response = self.start()
            job = self.wait_done(response.json()['id'])
        self.assertEqual(job['status'], 'failed')
        self.assertIn('Quota', job['error'])
        directory = Path(self.temp.name) / 'validation-jobs'
        path = directory / (job['id'] + '.json')
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        manager = ValidationJobs(Path(self.temp.name), asyncio.Semaphore(2), GeminiRequests(), AsyncMock())
        self.assertEqual(manager.get(self.client.app.state.accounts.resolve(self.client.cookies.get('memo_session'))['id'], job['id'])['error'], job['error'])
        self.login('other')
        self.assertEqual(self.client.get('/api/validation-jobs/' + job['id']).status_code, 404)
        self.assertEqual(self.client.post(f'/api/validation-jobs/{job["id"]}/read', headers=self.headers, json={}).status_code, 404)

    def test_incomplete_results_cannot_claim_coverage(self):
        with patch('backend.main.validate_coverage', new_callable=AsyncMock, return_value={'covered': True, 'proposals': [], 'checked_pages': 1, 'checked_cards': 1}):
            response = self.start()
            job = self.wait_done(response.json()['id'])
        self.assertEqual(job['status'], 'failed')
        self.assertIsNone(job['result'])

    def test_saving_a_draft_links_its_existing_job_without_a_second_validation(self):
        with patch('backend.main.validate_coverage', new_callable=AsyncMock, return_value={'covered': True, 'proposals': [], 'checked_pages': 3, 'checked_cards': 1}) as service:
            response = self.start()
            identifier = response.json()['id']
            self.wait_done(identifier)
            deck = self.client.post('/api/sets', json={'title': 'Saved', 'cards': CARDS, 'document_ids': [self.document['id']]}, headers=self.headers).json()
            link = self.client.post('/api/validation-jobs/link', json={'set_id': deck['id'], 'draft_id': 'draft-1'}, headers=self.headers)
            self.assertEqual(link.status_code, 200, link.text)
            self.assertEqual(self.client.get('/api/validation-jobs/' + identifier).json()['set_id'], deck['id'])
            service.assert_awaited_once()
        self.login('other')
        self.assertEqual(self.client.post('/api/validation-jobs/link', json={'set_id': deck['id'], 'draft_id': 'draft-1'}, headers=self.headers).status_code, 404)

    def test_running_checkpoint_is_recoverable_after_server_restart(self):
        path = Path(self.temp.name) / 'validation-jobs' / 'interrupted.json'
        path.write_text(json.dumps({'id': 'interrupted', 'owner': 'owner', 'status': 'running', 'updated_at': time.time()}))
        manager = ValidationJobs(Path(self.temp.name), asyncio.Semaphore(2), GeminiRequests(), AsyncMock())
        self.assertEqual(manager.jobs['interrupted']['status'], 'failed')
        self.assertIn('redémarré', manager.jobs['interrupted']['error'])


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_queued_jobs_share_slots_and_shutdown_marks_interruption(self):
        import tempfile
        started = []
        release = asyncio.Event()
        async def validate(cards, documents, **kwargs):
            started.append(cards[0]['term'])
            await release.wait()
            return {'covered': True, 'proposals': [], 'checked_pages': 3, 'checked_cards': 1}
        with tempfile.TemporaryDirectory() as directory:
            manager = ValidationJobs(directory, asyncio.Semaphore(1), GeminiRequests(), validate)
            documents = [{'id': 'doc', 'name': 'Cours.pdf', 'kind': 'pdf', 'page_count': 3}]
            def snapshot(name):
                return {'title': name, 'description': '', 'set_id': None, 'draft_id': name,
                        'document_ids': ['doc'], 'cards': [{'term': name, 'definition': 'Answer'}]}
            first = manager.start('one', snapshot('first'), documents)
            second = manager.start('two', snapshot('second'), documents)
            await asyncio.sleep(0)
            self.assertEqual(started, ['first'])
            self.assertEqual(manager.get('two', second['id'])['status'], 'queued')
            self.assertEqual(manager.start('two', snapshot('second'), documents)['id'], second['id'])
            await manager.close()
            self.assertEqual(manager.get('one', first['id'])['status'], 'failed')
            self.assertEqual(manager.get('two', second['id'])['status'], 'failed')
            self.assertTrue(manager.get('two', second['id'])['unread'])
            restarted = ValidationJobs(directory, asyncio.Semaphore(1), GeminiRequests(), validate)
            self.assertEqual(restarted.get('one', first['id'])['status'], 'failed')
