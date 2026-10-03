"""Exercise card interactions without touching saved progress.

Widget checks run when a display is available; flow checks also run headlessly.
"""
import json
import random
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from flashcard_learn import FlashcardLearnApp
from study_engine import Phase, Question, StudyConfig, StudySession


class FlashcardFlowTests(unittest.TestCase):
    def setUp(self):
        self.app = FlashcardLearnApp.__new__(FlashcardLearnApp)
        self.now = 1000.
        self.app.session = StudySession([('Terme A', 'Définition A'), ('Terme B', 'Définition B')],
                                        config=StudyConfig(allow_multiple_choice=False, allow_reverse_direction=False),
                                        rng=random.Random(2), clock=lambda: self.now)
        self.app.scheduler = self.app.session
        self.app.session_correct = self.app.session_wrong = self.app.streak = 0
        self.app.awaiting_continue = False
        self.app.card_history = []
        self.app.history_index = -1
        self.app.history_context = None
        self.app.transition_message = ''
        for name in ('side_label', 'flip_hint', 'wrong_btn', 'correct_btn', 'round_notice',
                     'answer_entry', 'submit_btn', 'continue_btn', 'previous_btn', 'next_btn', '_save_progress',
                     '_set_card_text', 'update_stats', 'after'):
            setattr(self.app, name, Mock())
        self.app.load_next_card()

    def test_grade_requires_revealed_definition(self):
        question = self.app.question
        self.app.grade(True)
        self.app.grade(False)
        self.assertEqual(self.app.session.step, 0)
        self.assertEqual(self.app.question, question)
        self.app.wrong_btn.configure.assert_called_with(state='disabled')
        self.app.correct_btn.configure.assert_called_with(state='disabled')

    def test_click_reveals_definition_and_accepts_either_grade(self):
        for knew_it in (False, True):
            question = self.app.question
            self.app.flip_card(event=Mock())
            self.app._set_card_text.assert_called_with(question.answer, 16)
            self.app.wrong_btn.configure.assert_called_with(state='normal')
            self.app.grade(knew_it)
            self.assertFalse(self.app.showing_definition)
            self.assertNotEqual(self.app.question.card_id, question.card_id)
            self.app._set_card_text.assert_called_with(self.app.question.prompt, 18)
        self.assertEqual(self.app.session.session_correct, 1)
        self.assertEqual(self.app.session.session_wrong, 1)

    def test_space_toggles_both_sides_then_explicit_grade_advances(self):
        question = self.app.question
        self.assertEqual(self.app._space_flip(Mock()), 'break')
        self.assertTrue(self.app.showing_definition)
        self.app.correct_btn.configure.assert_called_with(state='normal')
        self.app._space_flip(Mock())
        self.assertFalse(self.app.showing_definition)
        self.app._set_card_text.assert_called_with(question.prompt, 18)
        self.app.correct_btn.configure.assert_called_with(state='disabled')
        self.app.grade(True)
        self.assertEqual(self.app.session.step, 0)
        self.assertEqual(self.app.question, question)
        self.app._space_flip(Mock())
        self.app.grade(True)
        self.assertEqual(self.app.session.session_correct, 1)
        self.app.grade(False)
        self.assertEqual(self.app.session.step, 1)
        self.app._space_flip(Mock())
        self.app.grade(False)
        self.assertEqual(self.app.session.session_wrong, 1)

    def test_arrows_navigate_without_grading_and_restore_pending_card(self):
        first = self.app.question
        self.app.previous_btn.configure.assert_called_with(state='disabled')
        self.assertEqual(self.app.navigate_card(-1, Mock()), 'break')
        self.assertEqual(self.app.question, first)
        self.app.flip_card()
        self.assertEqual(self.app.navigate_card(1, Mock()), 'break')
        second = self.app.question
        self.assertNotEqual(first.card_id, second.card_id)
        self.assertEqual(self.app.session.step, 0)
        self.app.previous_btn.configure.assert_called_with(state='normal')
        self.app.navigate_card(-1)
        self.assertEqual(self.app.question, first)
        self.assertTrue(self.app.showing_definition)
        self.assertEqual(self.app.session.current_question, second)
        resumed = StudySession([('Terme A', 'Définition A'), ('Terme B', 'Définition B')])
        resumed.restore(self.app.session.to_dict())
        self.assertEqual(resumed.next_question(), second)
        self.app.correct_btn.configure.assert_called_with(state='disabled')
        self.app.grade(True)
        self.assertEqual(self.app.session.step, 0)
        self.app._space_flip(Mock())
        self.assertFalse(self.app.showing_definition)
        self.app.navigate_card(1)
        self.assertEqual(self.app.question, second)
        self.app.flip_card()
        self.app.grade(True)
        self.assertEqual(self.app.session.session_correct, 1)
        self.assertEqual(self.app.session.cards[1].correct_total, 1)

    def test_previous_graded_card_cannot_be_graded_twice(self):
        first = self.app.question
        self.app.flip_card()
        self.app.grade(True)
        pending = self.app.question
        self.app.navigate_card(-1)
        self.assertEqual(self.app.question, first)
        self.app.grade(False)
        self.app.grade(True)
        self.app._space_flip(Mock())
        self.app._space_flip(Mock())
        self.assertEqual(self.app.session.step, 1)
        self.assertEqual(self.app.session.session_correct, 1)
        self.assertEqual(self.app.session.session_wrong, 0)
        self.app.navigate_card(1)
        self.assertEqual(self.app.question, pending)
        self.assertEqual(self.app.session.current_question, pending)

    def test_pending_reverse_question_starts_with_term_and_flips_to_definition(self):
        card = self.app.current_card
        self.app.session.current_question = Question(card.id, 'free_recall', 'reverse', card.definition, card.term)
        self.app.load_next_card()
        self.app.side_label.configure.assert_called_with(text='TERME → DÉFINITION')
        self.app._set_card_text.assert_called_with(card.term, 18)
        self.assertEqual(self.app.question.direction, 'forward')
        self.assertEqual(self.app.session.current_question, self.app.question)
        self.app._space_flip(Mock())
        self.app.side_label.configure.assert_called_with(text='DÉFINITION')
        self.app._set_card_text.assert_called_with(card.definition, 16)
        self.app._space_flip(Mock())
        self.app._set_card_text.assert_called_with(card.term, 18)
        self.assertEqual(self.app.session.step, 0)
        self.app._space_flip(Mock())
        self.app.grade(True)
        self.assertEqual(card.history[-1]['direction'], 'forward')

    def test_typed_answer_shows_correction_then_space_toggles_without_advancing(self):
        self.app.session = StudySession([('a', 'alpha'), ('b', 'beta')],
                                        config=StudyConfig(allow_multiple_choice=False, allow_typed_recall=True))
        self.app.load_next_card()
        q = self.app.question
        self.assertEqual(q.kind, 'typed')
        self.app.grade(True)
        self.assertEqual(self.app.session.step, 0)
        self.app.answer_entry.get.return_value = 'incorrect'
        self.app.submit_answer()
        self.assertEqual(self.app.session.session_wrong, 1)
        self.assertTrue(self.app.awaiting_continue)
        self.app.side_label.configure.assert_called_with(text='CORRECTION')
        self.app._set_card_text.assert_called_with(q.answer, 16)
        self.app._save_progress.assert_called()
        self.app.submit_answer()
        self.app.grade(True)
        self.assertEqual(self.app.session.step, 1)
        self.app._space_flip(Mock())
        self.assertTrue(self.app.awaiting_continue)
        self.assertFalse(self.app.showing_definition)
        self.assertEqual(self.app.question, q)
        self.app._set_card_text.assert_called_with(q.prompt, 18)
        self.app._space_flip(Mock())
        self.app._set_card_text.assert_called_with(q.answer, 16)
        self.assertEqual(self.app.session.step, 1)
        self.app.navigate_card(1)
        self.assertFalse(self.app.awaiting_continue)
        self.assertNotEqual(self.app.question.card_id, q.card_id)

    def test_multiple_choice_session_displays_only_flashcards(self):
        self.app.session = StudySession([('a', 'alpha'), ('b', 'beta')], rng=random.Random(2))
        original = self.app.session.next_question()
        self.assertEqual(original.kind, 'multiple_choice')
        self.app.load_next_card()
        self.assertEqual(self.app.question.card_id, original.card_id)
        self.assertEqual(self.app.question.kind, 'free_recall')
        self.assertEqual(self.app.question.options, ())
        self.assertEqual(self.app.session.current_question, self.app.question)
        self.app._set_card_text.assert_called_with(original.prompt, 18)
        self.app.correct_btn.configure.assert_called_with(state='disabled')
        self.app._space_flip(Mock())
        self.app.wrong_btn.configure.assert_called_with(state='normal')
        self.app.correct_btn.configure.assert_called_with(state='normal')
        self.assertEqual(self.app.session.step, 0)
        self.app._space_flip(Mock())
        self.app._set_card_text.assert_called_with(original.prompt, 18)
        self.app._space_flip(Mock())
        self.app.grade(True)
        self.assertEqual(self.app.session.session_correct, 1)
        self.assertEqual(self.app.session.cards[0].history[-1]['response_type'], 'free_recall')

    def test_saved_multiple_choice_resumes_as_flashcard_without_losing_progress(self):
        self.app.session = StudySession([('a', 'alpha'), ('b', 'beta')])
        self.app.session.next_question()
        self.app.session.grade(False)
        original = self.app.session.next_question()
        saved = self.app.session.to_dict()
        self.app.session = StudySession([('a', 'alpha'), ('b', 'beta')])
        with patch('flashcard_learn.PROGRESS_PATH') as path:
            path.read_text.return_value = json.dumps(saved)
            self.app._load_progress()
        self.app.load_next_card()
        self.assertFalse(self.app.session.config.allow_multiple_choice)
        self.assertIs(self.app.session.questions.config, self.app.session.config)
        self.assertEqual(self.app.question.card_id, original.card_id)
        self.assertEqual(self.app.question.kind, 'free_recall')
        self.assertEqual(self.app.question.options, ())
        self.assertEqual(self.app.session.step, 1)
        self.assertEqual(self.app.session.session_wrong, 1)
        self.assertEqual(self.app.session.cards[0].mistakes, 1)
        self.assertEqual(self.app.session.to_dict()['cards'], saved['cards'])
        self.assertEqual(self.app.session.to_dict()['rounds'], saved['rounds'])
        self.assertEqual(self.app.session.to_dict()['current_question']['kind'], 'free_recall')

    def test_saved_reverse_questions_resume_term_first_without_losing_progress(self):
        deck = [('a', 'alpha'), ('b', 'beta')]
        for kind in ('free_recall', 'typed', 'multiple_choice'):
            with self.subTest(kind=kind):
                source = StudySession(deck, config=StudyConfig(allow_reverse_direction=True,
                                                               allow_typed_recall=kind == 'typed'),
                                      rng=random.Random(2), clock=lambda: self.now)
                source.next_question()
                source.grade(False)
                pending = source.next_question()
                card = next(c for c in source.cards if c.id == pending.card_id)
                options = tuple(c.term for c in source.cards) if kind == 'multiple_choice' else ()
                source.current_question = Question(card.id, kind, 'reverse', card.definition, card.term, options)
                saved = source.to_dict()
                self.app.session = StudySession(deck, clock=lambda: self.now)
                with patch('flashcard_learn.PROGRESS_PATH') as path:
                    path.read_text.return_value = json.dumps(saved)
                    self.app._load_progress()
                self.app.load_next_card()
                self.assertFalse(self.app.session.config.allow_reverse_direction)
                self.assertIs(self.app.session.questions.config, self.app.session.config)
                self.assertEqual(self.app.question,
                                 Question(card.id, 'free_recall' if kind == 'multiple_choice' else kind,
                                          'forward', card.term, card.definition))
                self.assertEqual(self.app.session.current_question, self.app.question)
                self.app._set_card_text.assert_called_with(card.term, 18)
                self.assertFalse(self.app.showing_definition)
                self.assertEqual(self.app.session.step, saved['step'])
                self.assertEqual(self.app.session.session_wrong, saved['session_wrong'])
                self.assertEqual(self.app.session.to_dict()['cards'], saved['cards'])
                self.assertEqual(self.app.session.to_dict()['rounds'], saved['rounds'])
                self.assertEqual(self.app.session.to_dict()['current_question']['direction'], 'forward')

    def test_typed_answers_and_shortcuts_preserve_text_entry(self):
        self.app.session = StudySession([('a', 'some answer'), ('b', 'other')],
                                        config=StudyConfig(allow_multiple_choice=False, allow_typed_recall=True))
        self.app.load_next_card()
        self.assertEqual(self.app.question.kind, 'typed')
        self.app.answer_entry.get.return_value = '  SOME   Answer '
        event = Mock(widget=self.app.answer_entry)
        self.assertIsNone(self.app._space_flip(event))
        self.assertIsNone(self.app.navigate_card(-1, event))
        self.assertIsNone(self.app.navigate_card(1, event))
        self.assertEqual(self.app.session.step, 0)
        self.assertEqual(self.app.submit_answer(), 'break')
        self.assertEqual(self.app.session.session_correct, 1)
        # A hidden entry must not suppress flipping or navigation shortcuts.
        self.assertEqual(self.app._space_flip(event), 'break')
        self.assertTrue(self.app.awaiting_continue)
        self.assertFalse(self.app.showing_definition)
        self.assertEqual(self.app.navigate_card(1, event), 'break')
        self.assertFalse(self.app.awaiting_continue)
        self.app.answer_entry.get.return_value = 'wrong'
        self.app.submit_answer()
        self.assertEqual(self.app.session.session_wrong, 1)
        self.app.side_label.configure.assert_called_with(text='CORRECTION')

    def test_typed_draft_survives_visiting_previous_card(self):
        self.app.session = StudySession([('a', 'alpha'), ('b', 'beta')],
                                        config=StudyConfig(allow_multiple_choice=False, allow_typed_recall=True))
        self.app.load_next_card()
        self.app.answer_entry.get.return_value = 'first draft'
        self.app.navigate_card(1)
        pending = self.app.question
        self.app.answer_entry.get.return_value = 'second draft'
        self.app.navigate_card(-1)
        self.app.submit_answer()
        self.app.navigate_card(1)
        self.app.answer_entry.insert.assert_called_with(0, 'second draft')
        self.assertEqual(self.app.session.current_question, pending)
        self.assertEqual(self.app.session.step, 0)

    def test_empty_typed_response_is_not_graded(self):
        self.app.session = StudySession([('a', 'alpha')],
                                        config=StudyConfig(allow_typed_recall=True))
        self.app.load_next_card()
        self.app.answer_entry.get.return_value = '   '
        self.app.submit_answer()
        self.assertEqual(self.app.session.step, 0)

    def test_final_round_appears_before_completion_screen(self):
        self.app.session = StudySession([('a', 'alpha')],
                                        config=StudyConfig(allow_reverse_direction=False), clock=lambda: self.now)
        self.app.load_next_card()
        while self.app.session.phase == Phase.INITIAL_ROUND_LEARNING:
            self.now += 301
            self.app.flip_card()
            self.app.grade(True)
        self.assertEqual(self.app.session.phase, Phase.FINAL_MASTERY_ROUND)
        self.assertIsNotNone(self.app.current_card)
        self.assertIn('Maîtrise finale', self.app.transition_message)
        self.assertFalse(self.app.session.complete)
        self.assertEqual(len(self.app.card_history), 1)
        self.app.previous_btn.configure.assert_called_with(state='disabled')
        while not self.app.session.complete:
            self.now += 301
            self.app.flip_card()
            self.app.grade(True)
        self.assertIsNone(self.app.current_card)
        self.app.side_label.configure.assert_called_with(text='ENSEMBLE MAÎTRISÉ')
        self.app.after.assert_not_called()
        self.app.previous_btn.configure.assert_called_with(state='disabled')
        self.app.next_btn.configure.assert_called_with(state='disabled')

    def test_review_mode_is_explicit_and_empty_review_does_not_finish_set(self):
        self.app.toggle_mode()
        self.assertEqual(self.app.session.mode, 'REVIEW')
        self.assertFalse(self.app.session.complete)
        self.app.side_label.configure.assert_called_with(text='RÉVISIONS À JOUR')
        self.app.after.assert_called_once()
        self.app.toggle_mode()
        self.assertEqual(self.app.session.mode, 'LEARN')
        self.assertIsNotNone(self.app.current_card)
        pending = self.app.question
        self.app._check_reviews()
        self.assertEqual(self.app.question, pending)

    def test_statistics_distinguish_initial_final_complete_and_review(self):
        for name in ('progress_fill', 'counter_label', 'mode_btn', 'status_label', 'streak_label', 'heading_label'):
            setattr(self.app, name, Mock())
        FlashcardLearnApp.update_stats(self.app)
        self.app.counter_label.configure.assert_called_with(text='Groupe 1/1 · 0/2')
        self.app.progress_fill.place.assert_called_with(relwidth=0)
        while self.app.session.phase == Phase.INITIAL_ROUND_LEARNING:
            self.app.session.next_question()
            self.app.session.grade(True)
        self.app.current_card = None
        FlashcardLearnApp.update_stats(self.app)
        self.app.counter_label.configure.assert_called_with(text='Maîtrise finale · 0/2')
        self.app.progress_fill.place.assert_called_with(relwidth=.5)
        self.app.session.set_mode('REVIEW')
        FlashcardLearnApp.update_stats(self.app)
        self.app.counter_label.configure.assert_called_with(text='Révision espacée · 0 à revoir')
        self.app.mode_btn.configure.assert_called_with(text='Apprendre', state='normal')
        self.app.session.set_mode('LEARN')
        while not self.app.session.complete:
            self.app.session.next_question()
            self.app.session.grade(True)
        FlashcardLearnApp.update_stats(self.app)
        self.app.counter_label.configure.assert_called_with(text='Ensemble maîtrisé · 2/2')
        self.app.progress_fill.place.assert_called_with(relwidth=1)


class FlashcardWidgetTests(unittest.TestCase):
    def setUp(self):
        self.deck = [('Terme A', 'Une longue définition.\n' * 60), ('Terme B', 'Définition B')]
        self.enterContext(patch('flashcard_learn.FLASHCARDS', self.deck))
        self.enterContext(patch.object(FlashcardLearnApp, '_load_progress'))
        self.enterContext(patch.object(FlashcardLearnApp, '_save_progress'))
        try:
            self.app = FlashcardLearnApp(config=StudyConfig(allow_multiple_choice=False,
                                                          allow_reverse_direction=False))
        except tk.TclError as error:
            self.skipTest(f'Tk display unavailable: {error}')
        self.addCleanup(self.app.destroy)
        self.app.update()
        self.app.focus_force()

    def press(self, key, widget=None):
        (widget or self.app).event_generate(f'<KeyPress-{key}>')
        self.app.update()

    def test_grading_and_navigation_buttons_fit_at_default_and_minimum_size(self):
        self.app.flip_card()
        for width, height in ((980, 720), (760, 600)):
            with self.subTest(size=(width, height)):
                self.app.geometry(f'{width}x{height}')
                self.app.update()
                for button in (self.app.wrong_btn, self.app.correct_btn,
                               self.app.previous_btn, self.app.next_btn):
                    self.assertTrue(button.winfo_ismapped())
                    x = button.winfo_rootx() - self.app.winfo_rootx()
                    y = button.winfo_rooty() - self.app.winfo_rooty()
                    self.assertGreaterEqual(x, 0)
                    self.assertGreaterEqual(y, 0)
                    self.assertLessEqual(x + button.winfo_width(), width)
                    self.assertLessEqual(y + button.winfo_height(), height)
                self.assertEqual(self.app.wrong_btn['state'], 'normal')
                self.assertEqual(self.app.correct_btn['state'], 'normal')
                self.assertGreater(self.app.card_text.winfo_height(), 20)

    def test_space_and_arrows_work_with_focused_text_and_buttons(self):
        first = self.app.question
        self.app.card_text.focus_force()
        self.press('space', self.app.card_text)
        self.assertTrue(self.app.showing_definition)
        self.app.correct_btn.focus_force()
        self.press('space', self.app.correct_btn)
        self.assertFalse(self.app.showing_definition)
        self.assertEqual(self.app.session.step, 0)
        self.press('space', self.app.correct_btn)
        self.press('Right', self.app.correct_btn)
        second = self.app.question
        self.assertNotEqual(first.card_id, second.card_id)
        self.assertEqual(self.app.session.step, 0)
        self.press('Left', self.app.card_text)
        self.assertEqual(self.app.question, first)
        self.press('Right', self.app.card_text)
        self.assertEqual(self.app.question, second)
        self.press('space', self.app.card_text)
        self.app.correct_btn.invoke()
        self.assertEqual(self.app.session.session_correct, 1)

    def test_feedback_space_never_activates_focused_continue_button(self):
        self.app.session = StudySession(self.deck, config=StudyConfig(allow_multiple_choice=False,
                                                                     allow_typed_recall=True))
        self.app.load_next_card()
        question = self.app.question
        self.app.answer_entry.insert(0, question.answer)
        self.app.submit_btn.invoke()
        self.app.update()
        self.assertEqual(self.app.focus_get(), self.app.continue_btn)
        self.press('space', self.app.continue_btn)
        self.assertEqual(self.app.question, question)
        self.assertFalse(self.app.showing_definition)
        self.press('space', self.app.continue_btn)
        self.assertTrue(self.app.showing_definition)
        self.assertEqual(self.app.session.step, 1)
        self.press('Right', self.app.continue_btn)
        self.assertNotEqual(self.app.question.card_id, question.card_id)

    def test_number_keys_grade_like_buttons_after_revealing_answer(self):
        question = self.app.question
        self.app.card_text.focus_force()
        for key in ('1', '2'):
            self.press(key, self.app.card_text)
        self.assertEqual(self.app.question, question)
        self.assertEqual(self.app.session.step, 0)
        self.app.flip_card()
        self.press('1', self.app.card_text)
        self.assertEqual(self.app.session.session_wrong, 1)
        self.assertNotEqual(self.app.question.card_id, question.card_id)
        self.app.flip_card()
        self.app.correct_btn.focus_force()
        self.press('2', self.app.correct_btn)
        self.assertEqual(self.app.session.session_correct, 1)
        self.assertEqual(self.app.session.step, 2)
        self.assertFalse(self.app.showing_definition)
        self.app.flip_card()
        question = self.app.question
        self.app.navigate_card(-1)
        for key in ('1', '2', '3', '4'):
            self.press(key, self.app.card_text)
        self.assertEqual(self.app.session.step, 2)
        self.app.navigate_card(1)
        for key in ('3', '4'):
            self.press(key, self.app.card_text)
        self.assertEqual(self.app.question, question)
        self.assertEqual(self.app.session.step, 2)
        self.assertTrue(self.app.showing_definition)

    def test_typed_entry_keeps_space_and_cursor_arrows(self):
        self.app.session = StudySession(self.deck, config=StudyConfig(allow_multiple_choice=False,
                                                                     allow_typed_recall=True))
        self.app.load_next_card()
        self.app.update()
        entry = self.app.answer_entry
        entry.insert(0, 'alphabeta')
        entry.icursor(5)
        self.press('space', entry)
        self.assertEqual(entry.get(), 'alpha beta')
        self.press('Right', entry)
        self.assertEqual(entry.index('insert'), 7)
        self.press('Left', entry)
        self.assertEqual(entry.index('insert'), 6)
        self.press('1', entry)
        self.press('2', entry)
        self.assertEqual(entry.get(), 'alpha 12beta')
        self.assertEqual(self.app.session.step, 0)
        self.assertEqual(len(self.app.card_history), 1)
        self.app.card_text.event_generate('<Button-1>')
        self.app.update()
        self.assertTrue(self.app.showing_definition)
        self.assertEqual(self.app.correct_btn['state'], 'normal')


if __name__ == '__main__':
    unittest.main()
