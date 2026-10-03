import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.controller import WebStudy
from backend.main import create_app
from backend.study_engine import Question, StudyConfig, StudySession


CARDS = [("Terme " + str(i), "Définition " + str(i)) for i in range(4)]


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "progress.json"
        self.app = create_app(self.path, None, CARDS, StudyConfig(round_size=2))
        self.client = TestClient(self.app).__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.directory.cleanup()

    def state(self):
        response = self.client.get("/api/state")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def act(self, kind, **values):
        return self.client.post("/api/actions", json={"type": kind, "revision": self.state()["revision"], **values})

    def grade(self, correct=True):
        self.assertEqual(self.act("flip").status_code, 200)
        response = self.act("grade", correct=correct)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_load_and_reads_do_not_grade_or_advance(self):
        first = self.state()
        self.assertEqual(first, self.state())
        self.assertEqual(first["question"]["kind"], "free_recall")
        self.assertEqual((first["correct"], first["wrong"]), (0, 0))
        self.assertEqual(len(first["active_cards"]), 2)
        self.assertEqual(self.client.get("/api/state").headers["cache-control"], "no-store")

    def test_must_reveal_before_grading_and_grade_is_strict_boolean(self):
        self.assertEqual(self.act("grade", correct=True).status_code, 400)
        self.assertEqual(self.act("grade", correct=1).status_code, 422)
        self.assertEqual(self.act("grade", correct="false").status_code, 422)
        self.assertEqual(self.state()["correct"], 0)
        state = self.grade()
        self.assertEqual((state["correct"], state["streak"]), (1, 1))
        self.assertFalse(state["question"]["showing_answer"])

    def test_incorrect_answer_resets_streak(self):
        self.grade()
        state = self.grade(False)
        self.assertEqual((state["correct"], state["wrong"], state["streak"]), (1, 1, 0))

    def test_navigation_does_not_grade_and_previous_cannot_be_regraded(self):
        original = self.state()["question"]["text"]
        self.act("navigate", direction=1)
        previous = self.act("navigate", direction=-1).json()
        self.assertTrue(previous["question"]["historical"])
        self.assertEqual(previous["question"]["text"], original)
        self.act("flip")
        self.assertEqual(self.act("grade", correct=True).status_code, 400)
        self.assertEqual((self.state()["correct"], self.state()["wrong"]), (0, 0))
        self.assertFalse(self.act("navigate", direction=1).json()["question"]["historical"])

    def test_stale_request_cannot_double_grade(self):
        revealed = self.act("flip").json()
        body = {"type": "grade", "correct": True, "revision": revealed["revision"]}
        self.assertEqual(self.client.post("/api/actions", json=body).status_code, 200)
        self.assertEqual(self.client.post("/api/actions", json=body).status_code, 409)
        self.assertEqual(self.state()["correct"], 1)

    def test_typed_response_normalizes_case_whitespace_and_requires_text(self):
        self.act("settings", typed=True)
        self.assertEqual(self.state()["question"]["kind"], "typed")
        self.assertEqual(self.act("typed", response="  ").status_code, 400)
        expected = self.app.state.study.view.question.answer
        response = self.act("typed", response="  " + expected.upper().replace(" ", "   ") + "\n").json()
        self.assertEqual(response["correct"], 1)
        self.assertTrue(response["question"]["answered"])
        self.assertTrue(response["question"]["showing_answer"])
        self.assertEqual(self.act("typed", response=expected).status_code, 400)
        self.act("flip")
        self.assertEqual(self.state()["correct"], 1)
        self.act("navigate", direction=1)
        self.assertFalse(self.state()["question"]["answered"])

    def test_typed_incorrect_feedback_and_flip_fallback(self):
        self.act("settings", typed=True)
        state = self.act("typed", response="wrong").json()
        self.assertFalse(state["question"]["correct"])
        self.assertEqual(state["wrong"], 1)
        self.act("navigate", direction=1)
        state = self.act("flip").json()
        self.assertEqual(state["question"]["kind"], "free_recall")
        self.assertTrue(state["question"]["can_grade"])

    def test_typed_draft_survives_history_navigation(self):
        self.grade()
        self.act("settings", typed=True)
        self.act("navigate", direction=-1, response="Mon brouillon 12")
        state = self.act("navigate", direction=1).json()
        self.assertEqual(state["question"]["typed_response"], "Mon brouillon 12")

    def test_restart_resumes_pending_question_and_all_counts(self):
        self.grade()
        self.grade(False)
        original = self.state()
        with TestClient(create_app(self.path, None, CARDS)) as client:
            loaded = client.get("/api/state").json()
            for key in ("correct", "wrong", "streak", "phase", "progress"):
                self.assertEqual(original[key], loaded[key])
            self.assertEqual(original["question"]["card_id"], loaded["question"]["card_id"])
            self.assertNotEqual(original["revision"], loaded["revision"])

    def test_atomic_save_failure_rolls_back_grade_and_revision(self):
        self.act("flip")
        original = self.state()
        saved = self.path.read_bytes()
        with patch("backend.controller.os.replace", side_effect=OSError("disk full")):
            self.assertEqual(self.act("grade", correct=True).status_code, 503)
        self.assertEqual(original, self.state())
        self.assertEqual(saved, self.path.read_bytes())
        self.assertEqual(list(self.path.parent.glob(".progress-*")), [])
        self.assertEqual(self.act("grade", correct=True).status_code, 200)
        self.assertEqual(self.state()["correct"], 1)

    def test_import_original_progress_once_and_reset_only_web_progress(self):
        self.grade()
        source = Path(self.directory.name) / "desktop.json"
        source.write_bytes(self.path.read_bytes())
        desktop_bytes = source.read_bytes()
        web_path = Path(self.directory.name) / "separate" / "progress.json"
        with TestClient(create_app(web_path, source, CARDS)) as client:
            state = client.get("/api/state").json()
            self.assertEqual(state["correct"], 1)
            response = client.post("/api/actions", json={"type": "reset", "revision": state["revision"]})
            self.assertEqual(response.json()["correct"], 0)
        self.assertEqual(source.read_bytes(), desktop_bytes)
        with TestClient(create_app(web_path, source, CARDS)) as client:
            self.assertEqual(client.get("/api/state").json()["correct"], 0)

    def test_old_multiple_choice_prompt_converts_to_flashcard(self):
        legacy = StudySession(CARDS)
        self.assertEqual(legacy.next_question().kind, "multiple_choice")
        source = Path(self.directory.name) / "old.json"
        source.write_text(json.dumps(legacy.to_dict()))
        controller = WebStudy(Path(self.directory.name) / "new.json", source, CARDS)
        self.assertEqual(controller.view.question.kind, "free_recall")
        self.assertFalse(controller.session.config.allow_multiple_choice)

    def test_saved_reverse_prompts_resume_term_first_with_the_same_card(self):
        for kind in ("free_recall", "typed", "multiple_choice"):
            with self.subTest(kind=kind):
                legacy = StudySession(CARDS, StudyConfig(allow_reverse_direction=True))
                legacy.next_question()
                card = legacy.cards[0]
                options = tuple(c.term for c in legacy.cards) if kind == "multiple_choice" else ()
                legacy.current_question = Question(card.id, kind, "reverse", card.definition, card.term, options)
                source = Path(self.directory.name) / f"reverse-{kind}.json"
                source.write_text(json.dumps(legacy.to_dict()))
                controller = WebStudy(Path(self.directory.name) / f"forward-{kind}.json", source, CARDS)
                question = controller.view.question
                self.assertEqual((question.card_id, question.direction, question.prompt, question.answer),
                                 (card.id, "forward", card.term, card.definition))
                self.assertFalse(controller.session.config.allow_reverse_direction)
                self.assertEqual(controller.session.step, legacy.step)

    def test_invalid_web_save_is_not_overwritten(self):
        source = Path(self.directory.name) / "broken.json"
        source.write_text('{"version": 42}')
        before = source.read_bytes()
        with self.assertRaises(ValueError):
            WebStudy(source, None, CARDS)
        self.assertEqual(source.read_bytes(), before)

    def test_review_unlock_initial_final_transitions_and_review_is_separate(self):
        self.assertEqual(self.act("mode", mode="REVIEW").status_code, 400)
        seen_final = False
        for _ in range(200):
            state = self.state()
            if state["complete"]:
                break
            if state["phase"] == "FINAL_MASTERY_ROUND":
                seen_final = True
                self.assertLess(state["progress"], 1)
            self.grade()
        self.assertTrue(seen_final)
        self.assertTrue(self.state()["complete"])
        self.assertEqual(self.state()["progress"], 1)
        self.assertEqual(self.state()["active_mastered"], 4)
        initial = [copy.deepcopy(c.history) for c in self.app.state.study.session.cards]
        final = [copy.deepcopy(c.final.history) for c in self.app.state.study.session.cards]
        self.app.state.study.session.clock = lambda: 1e12
        reviewed = self.act("mode", mode="REVIEW").json()
        self.assertEqual(reviewed["mode"], "REVIEW")
        self.assertIsNotNone(reviewed["question"])
        self.grade(False)
        self.assertEqual([c.history for c in self.app.state.study.session.cards], initial)
        self.assertEqual([c.final.history for c in self.app.state.study.session.cards], final)
        self.assertEqual(self.state()["progress"], 1)
        self.assertTrue(self.state()["complete"])

    def test_empty_review_queue_and_return_to_learning(self):
        for _ in range(100):
            if self.state()["review_available"]:
                break
            self.grade()
        self.assertTrue(self.state()["review_available"])
        reviewed = self.act("mode", mode="REVIEW").json()
        self.assertIsNone(reviewed["question"])
        self.assertEqual(self.act("refresh").status_code, 200)
        learned = self.act("mode", mode="LEARN").json()
        self.assertEqual(learned["mode"], "LEARN")
        self.assertIsNotNone(learned["question"])


if __name__ == "__main__":
    unittest.main()
