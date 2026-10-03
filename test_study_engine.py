"""Behavioral checks for closed rounds, final mastery, and saved progress."""
import copy
import json
import random
import unittest
from dataclasses import asdict, replace

from study_engine import (Phase, Question, RoundStatus, State, StudyConfig, StudySession)


class EngineTests(unittest.TestCase):
    def make(self, size=100, config=None):
        self.now = 1000.
        config = config or StudyConfig(allow_multiple_choice=False, allow_reverse_direction=False)
        return StudySession([(f'term{i}', f'definition{i}') for i in range(size)],
                            config=config, rng=random.Random(2), clock=lambda: self.now)

    def answer_card(self, session, card, correct=True, kind='free_recall'):
        """Choose a permitted test card explicitly to probe mastery and boundaries."""
        options = (card.definition, next(c.definition for c in session.active_pool if c.id != card.id)) if kind == 'multiple_choice' else ()
        session.current_question = Question(card.id, kind, 'forward', card.term, card.definition, options)
        session.grade(correct)

    def master_card(self, session, card, fillers=None, filler_correct=False):
        phase = session.phase
        for _ in range(20):
            if session.progress_for(card).mastered:
                return
            if len(session.active_pool) == 1:
                self.now += session.config.minimum_spacing + 1
            else:
                for other in (fillers or session.active_pool):
                    if other.id != card.id:
                        self.answer_card(session, other, filler_correct)
                        if session.phase != phase:
                            return
            self.answer_card(session, card)
            if session.phase != phase:
                return
        self.fail('Card never mastered')

    def finish_current_round(self, session):
        group = session.active_round
        for _ in range(2000):
            if session.active_round is not group:
                return
            session.next_question()
            if len(session.active_pool) == 1:
                self.now += session.config.minimum_spacing + 1
            session.grade(True)
        self.fail('Round never finished')

    def start_final(self, session):
        while session.phase == Phase.INITIAL_ROUND_LEARNING:
            self.finish_current_round(session)
        self.assertEqual(session.phase, Phase.FINAL_MASTERY_ROUND)

    def round_trip(self, session, raw_cards=None):
        data = json.loads(json.dumps(session.to_dict()))
        raw_cards = raw_cards or [(c.term, c.definition) for c in session.cards]
        restored = StudySession(raw_cards, clock=lambda: self.now)
        restored.restore(data)
        return restored

    def test_ordered_round_assignments_and_short_last_round(self):
        s = self.make(37)
        self.assertEqual([len(r.card_ids) for r in s.rounds], [10, 10, 10, 7])
        self.assertEqual([r.status for r in s.rounds], [RoundStatus.ACTIVE] + [RoundStatus.LOCKED] * 3)
        self.assertEqual([c.round_id for c in s.cards], [i // 10 for i in range(37)])

    def test_thousands_of_selections_never_expose_future_cards(self):
        s = self.make()
        allowed = {c.id for c in s.cards[:10]}
        for _ in range(3000):
            question = s.next_question()
            self.assertIn(question.card_id, allowed)
            self.assertIn(question.prompt, {c.term for c in s.cards[:10]})
            s.grade(False)
        self.assertTrue(all(c.state == State.NEW and not c.history for c in s.cards[10:]))
        self.assertEqual(s.current_round_index, 0)

    def test_first_pass_introduces_every_card_before_repeating(self):
        s = self.make(15)
        first_pass = []
        for _ in range(10):
            first_pass.append(s.next_question().card_id)
            s.grade(False)
        self.assertEqual(first_pass, [c.id for c in s.cards[:10]])
        self.assertEqual(s.active_round.introduced_ids, first_pass)
        self.assertTrue(all(c.state == State.NEW for c in s.cards[10:]))

    def test_mastering_one_card_does_not_replace_or_unlock_any_card(self):
        s = self.make(12)
        card = s.cards[0]
        self.master_card(s, card)
        self.assertTrue(card.mastered)
        self.assertEqual(s.active_pool, s.cards[:10])
        self.assertEqual(s.rounds[1].status, RoundStatus.LOCKED)
        self.assertEqual(s.cards[10].state, State.NEW)

    def test_nine_mastered_one_struggling_keeps_next_round_locked(self):
        s = self.make(20)
        # Target the same nine cards; no evidence is given for the tenth.
        for _ in range(8):
            for card in s.cards[:9]:
                self.answer_card(s, card)
        self.assertTrue(all(c.mastered for c in s.cards[:9]))
        self.assertFalse(s.cards[9].mastered)
        for _ in range(500):
            question = s.next_question()
            self.assertIn(question.card_id, {c.id for c in s.cards[:10]})
            s.grade(question.card_id != s.cards[9].id)
        self.assertEqual(s.rounds[1].status, RoundStatus.LOCKED)
        self.assertEqual(s.current_round_index, 0)

    def test_round_transitions_only_when_all_cards_mastered(self):
        s = self.make(20)
        self.finish_current_round(s)
        self.assertEqual(s.rounds[0].status, RoundStatus.COMPLETED)
        self.assertEqual(s.rounds[1].status, RoundStatus.ACTIVE)
        self.assertTrue(all(c.mastered for c in s.cards[:10]))
        self.assertEqual(s.active_pool, s.cards[10:])

    def test_previous_rounds_never_interrupt_even_when_reviews_due(self):
        s = self.make(30)
        self.finish_current_round(s)
        self.now += 10 ** 8
        for _ in range(500):
            self.assertIn(s.next_question().card_id, {c.id for c in s.cards[10:20]})
            s.grade(False)
        self.assertEqual(s.current_round_index, 1)
        self.assertTrue(all(c.mastered for c in s.cards[:10]))

    def test_incorrect_reinforcement_removes_mastery_and_blocks_transition(self):
        s = self.make(20)
        for _ in range(8):
            for card in s.cards[:9]:
                self.answer_card(s, card)
        card = s.cards[0]
        self.assertTrue(card.mastered)
        before = card.mastery_score
        self.answer_card(s, card, False)
        self.assertEqual(card.state, State.LEARNING)
        self.assertLess(card.mastery_score, before)
        self.assertEqual(card.consecutive_correct, 0)
        self.master_card(s, s.cards[9], fillers=s.cards[1:4], filler_correct=True)
        self.assertFalse(card.mastered)
        self.assertEqual(s.rounds[1].status, RoundStatus.LOCKED)

    def test_single_success_never_masters(self):
        s = self.make(2)
        self.answer_card(s, s.cards[0])
        self.assertFalse(s.cards[0].mastered)

    def test_immediate_correct_repetitions_do_not_supply_spaced_evidence(self):
        s = self.make(2)
        for _ in range(40):
            self.answer_card(s, s.cards[0])
        self.assertFalse(s.cards[0].mastered)
        self.assertEqual(s.cards[0].spaced_recalls, 0)
        self.assertEqual(s.cards[0].active_recalls, 0)

    def test_recognition_alone_cannot_master(self):
        s = self.make(2)
        for _ in range(30):
            for c in s.cards:
                self.answer_card(s, c, kind='multiple_choice')
        self.assertTrue(all(not c.mastered and c.active_recalls == 0 for c in s.cards))

    def test_meaningful_spacing_uses_intervening_questions(self):
        s = self.make(10)
        card = s.cards[0]
        self.answer_card(s, card)
        self.answer_card(s, s.cards[1])
        self.answer_card(s, s.cards[2])
        self.answer_card(s, card)
        self.assertFalse(card.history[-1]['strong_recall'])
        for c in s.cards[1:4]:
            self.answer_card(s, c)
        self.answer_card(s, card)
        self.assertTrue(card.history[-1]['strong_recall'])
        self.assertEqual(card.history[-1]['intervening_questions'], 3)
        self.assertEqual(card.history[-1]['spacing'], 0)

    def test_correction_followed_by_immediate_repeat_is_weak(self):
        s = self.make(10)
        c = s.cards[0]
        self.answer_card(s, c, False)
        self.answer_card(s, c)
        self.assertEqual(c.active_recalls, 0)
        for other in s.cards[1:4]:
            self.answer_card(s, other)
        self.answer_card(s, c)
        self.assertEqual(c.active_recalls, 1)
        self.assertFalse(c.mastered)

    def test_no_immediate_repetition_and_scheduler_spacing(self):
        s = self.make()
        ids = []
        for _ in range(300):
            q = s.next_question()
            self.assertNotIn(q.card_id, ids[-3:])
            ids.append(q.card_id)
            s.grade(False)

    def test_small_rounds_can_finish_and_singletons_need_elapsed_time(self):
        for size in (1, 2, 3, 7):
            with self.subTest(size=size):
                s = self.make(size)
                if size == 1:
                    for _ in range(30):
                        s.next_question()
                        s.grade(True)
                    self.assertFalse(s.cards[0].mastered)
                self.start_final(s)
                self.finish_current_round(s)
                self.assertTrue(s.complete)

    def test_weighted_selection_prefers_weak_cards_and_reinforces_mastered(self):
        s = self.make(10)
        for c in s.cards:
            c.state = State.MASTERED
            c.mastery_score = .95
        weak = s.cards[0]
        weak.state, weak.mastery_score = State.LEARNING, .1
        counts = {c.id: 0 for c in s.cards}
        for _ in range(4000):
            c = s.scheduler.select(s.active_pool, self.now, 100, introduced_ids=list(counts))
            counts[c.id] += 1
            for other in s.cards:
                other.last_seen_step = -1
        self.assertGreater(counts[weak.id], max(counts[c.id] for c in s.cards[1:]) * 4)
        self.assertTrue(all(value > 0 for value in counts.values()))

    def test_multiple_choice_content_is_limited_to_current_round(self):
        s = self.make(100, StudyConfig())
        for group_index in range(2):
            allowed = {c.definition for c in s.active_pool}
            for c in s.active_pool:
                for _ in range(25):
                    q = s.questions.select(c, s.active_pool)
                    self.assertEqual(q.kind, 'multiple_choice')
                    self.assertTrue(set(q.options) <= allowed)
            if group_index == 0:
                self.finish_current_round(s)

    def test_generator_rejects_a_card_outside_allowed_group(self):
        s = self.make(20)
        with self.assertRaises(ValueError):
            s.questions.select(s.cards[10], s.active_pool)

    def test_session_rejects_outside_questions_and_future_distractors(self):
        s = self.make(20)
        before = s.step
        for question in (Question(s.cards[10].id, 'free_recall', 'forward', s.cards[10].term, s.cards[10].definition),
                         Question(s.cards[0].id, 'multiple_choice', 'forward', s.cards[0].term, s.cards[0].definition,
                                  (s.cards[0].definition, s.cards[10].definition))):
            s.current_question = question
            with self.assertRaises(ValueError):
                s.next_question()
            with self.assertRaises(ValueError):
                s.grade(True)
        self.assertEqual(s.step, before)

    def test_question_difficulty_progresses_per_card_and_can_reverse(self):
        s = self.make(10, StudyConfig(allow_typed_recall=True, allow_reverse_direction=True))
        c = s.cards[0]
        self.assertEqual(s.questions.select(c, s.active_pool).kind, 'multiple_choice')
        c.state = State.FAMILIAR
        c.consecutive_correct = 2
        self.assertEqual(s.questions.select(c, s.active_pool).kind, 'typed')
        c.consecutive_correct = 3
        q = s.questions.select(c, s.active_pool)
        self.assertEqual((q.direction, q.prompt, q.answer), ('reverse', c.definition, c.term))
        self.assertEqual(s.questions.select(s.cards[1], s.active_pool).kind, 'multiple_choice')
        c.history = [dict(direction='reverse')]
        self.assertEqual(s.questions.select(c, s.active_pool).direction, 'forward')

    def test_default_questions_stay_term_first_through_learning_final_and_review(self):
        s = self.make(2, StudyConfig(allow_multiple_choice=False))
        phases = set()

        def check_question():
            question = s.next_question()
            self.assertIsNotNone(question)
            card = next(c for c in s.cards if c.id == question.card_id)
            self.assertEqual((question.direction, question.prompt, question.answer),
                             ('forward', card.term, card.definition))
            s.grade(True)

        for _ in range(100):
            if s.complete:
                break
            phases.add(s.phase)
            check_question()
        self.assertTrue(s.complete)
        self.assertEqual(phases, {Phase.INITIAL_ROUND_LEARNING, Phase.FINAL_MASTERY_ROUND})
        s.set_mode('REVIEW')
        for _ in range(10):
            self.now = max(c.review.next_review for c in s.cards) + 1
            check_question()

    def test_normal_round_completion_starts_final_instead_of_finishing(self):
        s = self.make(30)
        self.assertEqual(s.round_manager.final_round.status, RoundStatus.LOCKED)
        self.finish_current_round(s)
        self.assertEqual(s.round_manager.final_round.status, RoundStatus.LOCKED)
        self.start_final(s)
        self.assertFalse(s.complete)
        self.assertTrue(all(r.status == RoundStatus.COMPLETED for r in s.rounds))
        self.assertEqual(s.round_manager.final_round.status, RoundStatus.ACTIVE)
        self.assertEqual(s.active_pool, s.cards)
        self.assertTrue(all(c.mastered and c.final.state == State.UNTESTED for c in s.cards))
        self.assertEqual(s.mastered_count, 0)

    def test_final_first_pass_mixes_original_rounds_and_tests_every_card(self):
        s = self.make(30)
        self.start_final(s)
        self.assertIsNone(s.current_question)
        sequence = []
        for _ in range(30):
            q = s.next_question()
            sequence.append(next(c for c in s.cards if c.id == q.card_id))
            s.grade(True)
        self.assertEqual(len({c.id for c in sequence}), 30)
        self.assertGreater(len({c.round_id for c in sequence[:10]}), 1)
        self.assertNotEqual([c.id for c in sequence], [c.id for c in s.cards])
        self.assertTrue(all(c.final.attempts == 1 and not c.final.mastered for c in s.cards))

    def test_final_question_can_use_distractors_from_all_rounds(self):
        s = self.make(30, StudyConfig())
        self.start_final(s)
        c = s.cards[0]
        c.final.state = State.LEARNING
        seen = set()
        for _ in range(100):
            q = s.questions.select(c, s.active_pool, s.phase)
            seen.update(q.options)
        self.assertIn(s.cards[20].definition, seen)
        self.assertTrue(seen <= {c.definition for c in s.cards})

    def test_final_error_only_lowers_final_mastery(self):
        s = self.make(20)
        self.start_final(s)
        # Leave the last card untested so the round cannot close.
        for _ in range(8):
            for c in s.cards[:-1]:
                self.answer_card(s, c)
        c = s.cards[0]
        self.assertTrue(c.final.mastered)
        original = {key: copy.deepcopy(getattr(c, key)) for key in ('state', 'history', 'mastery_score', 'correct_total', 'mistakes')}
        self.answer_card(s, c, False)
        self.assertEqual(c.final.state, State.LEARNING)
        self.assertEqual(original, {key: getattr(c, key) for key in original})
        self.assertTrue(all(r.status == RoundStatus.COMPLETED for r in s.rounds))
        self.assertFalse(s.complete)

    def test_final_99_percent_never_finishes(self):
        s = self.make(100)
        self.start_final(s)
        for _ in range(8):
            for c in s.cards[:-1]:
                self.answer_card(s, c)
        self.assertEqual(s.mastered_count, 99)
        self.assertFalse(s.complete)
        self.assertEqual(s.active_pool, s.cards)
        self.finish_current_round(s)
        self.assertTrue(s.complete)
        self.assertEqual(s.mastered_count, 100)
        self.now += 10 ** 8
        self.assertIsNone(s.next_question())

    def test_save_reopen_halfway_through_third_round(self):
        s = self.make(40)
        self.finish_current_round(s)
        self.finish_current_round(s)
        self.master_card(s, s.cards[20])
        pending = s.next_question()
        restored = self.round_trip(s)
        self.assertEqual(restored.current_round_index, 2)
        self.assertEqual(restored.rounds[2].status, RoundStatus.ACTIVE)
        self.assertEqual(restored.rounds[3].status, RoundStatus.LOCKED)
        self.assertTrue(restored.cards[20].mastered)
        self.assertEqual(restored.next_question(), pending)
        self.assertEqual(json.loads(json.dumps(restored.to_dict())), json.loads(json.dumps(s.to_dict())))

    def test_final_progress_and_pending_question_survive_restart(self):
        s = self.make(20)
        self.start_final(s)
        for _ in range(10):
            s.next_question()
            s.grade(True)
        pending = s.next_question()
        restored = self.round_trip(s)
        self.assertEqual(restored.phase, Phase.FINAL_MASTERY_ROUND)
        self.assertEqual(restored.next_question(), pending)
        self.assertEqual([asdict(c.final) for c in restored.cards], [asdict(c.final) for c in s.cards])
        s.grade(True)
        restored.grade(True)
        self.assertEqual(s.next_question(), restored.next_question())

    def test_completed_progress_survives_restart(self):
        s = self.make(12)
        self.start_final(s)
        self.finish_current_round(s)
        restored = self.round_trip(s)
        self.assertTrue(restored.complete)
        self.assertIsNone(restored.next_question())

    def test_round_assignment_and_config_survive_deck_reordering(self):
        s = self.make(23, StudyConfig(round_size=7))
        s.next_question()
        s.grade(True)
        restored = self.round_trip(s, [(c.term, c.definition) for c in reversed(s.cards)])
        self.assertEqual(restored.config, s.config)
        self.assertEqual(restored.rounds, s.rounds)
        self.assertEqual([c.id for c in restored.active_pool], [c.id for c in s.active_pool])
        self.assertEqual({c.id: c.round_id for c in restored.cards}, {c.id: c.round_id for c in s.cards})

    def test_atomic_restore_rejects_invalid_state_and_leaks(self):
        s = self.make(20, StudyConfig())
        s.next_question()
        original = json.loads(json.dumps(s.to_dict()))
        mutations = [lambda d: d['cards'][0].update(mastery_score=2),
                     lambda d: d['rounds'][1].update(status='ACTIVE'),
                     lambda d: d.update(phase='COMPLETE'),
                     lambda d: d['final_round']['card_ids'].pop(),
                     lambda d: d['rounds'][0]['card_ids'].__setitem__(0, d['rounds'][1]['card_ids'][0]),
                     lambda d: d['current_question'].update(options=[s.cards[0].definition, s.cards[10].definition]),
                     lambda d: d['cards'][0]['final'].update(state='LEARNING'),
                     lambda d: d['cards'][0].update(stability=0)]
        for mutate in mutations:
            bad = copy.deepcopy(original)
            mutate(bad)
            with self.assertRaises(ValueError):
                s.restore(bad)
            self.assertEqual(json.loads(json.dumps(s.to_dict())), original)

    def test_legacy_migration_preserves_counts_without_inventing_mastery(self):
        data = dict(version=1, step=25, session_correct=5, session_wrong=20, streak=0,
                    cards=[dict(term=f'term{i}', definition=f'definition{i}',
                                correct_total=5 if i == 0 else 0, mistakes=20 if i == 0 else 0) for i in range(12)])
        s = self.make(12)
        s.restore(data)
        self.assertEqual(sum(c.mistakes for c in s.cards), 20)
        self.assertEqual(s.session_wrong, 20)
        self.assertEqual(s.active_pool, s.cards[:10])
        self.assertFalse(any(c.mastered for c in s.cards))
        self.assertEqual(s.rounds[1].status, RoundStatus.LOCKED)

    def test_version_two_migration_preserves_history_and_filters_pending_future(self):
        s = self.make(20)
        s.next_question()
        s.grade(False)
        fields = ('id', 'term', 'definition', 'state', 'history', 'correct_total', 'mistakes', 'attempts',
                  'consecutive_correct', 'spaced_recalls', 'active_recalls', 'mastery_score', 'recall_probability',
                  'last_reviewed', 'last_success', 'next_review', 'stability', 'successful_directions', 'last_seen_step')
        cards = [{key: getattr(c, key) for key in fields} for c in s.cards]
        for c in cards:
            if c['state'] == State.NEW:
                c['state'] = 'UNSEEN'
            c['last_seen_step'] = max(-999, c['last_seen_step'])
        future = s.cards[10]
        data = dict(version=2, cards=cards, step=s.step, session_correct=0, session_wrong=1, streak=0,
                    current_question=asdict(Question(future.id, 'free_recall', 'forward', future.term, future.definition)))
        restored = self.make(20)
        restored.restore(json.loads(json.dumps(data)))
        self.assertEqual(restored.cards[0].history, s.cards[0].history)
        self.assertIsNone(restored.current_question)
        self.assertIn(restored.next_question().card_id, {c.id for c in restored.cards[:10]})

    def test_separate_review_mode_does_not_change_learning_or_final_mastery(self):
        s = self.make(20)
        self.finish_current_round(s)
        self.now += 10 ** 8
        before = [(c.state, copy.deepcopy(c.history), asdict(c.final)) for c in s.cards]
        s.set_mode('REVIEW')
        question = s.next_question()
        self.assertIn(question.card_id, {c.id for c in s.cards[:10]})
        s.grade(False)
        self.assertEqual(before, [(c.state, c.history, asdict(c.final)) for c in s.cards])
        self.assertEqual(s.current_round_index, 1)
        self.assertEqual(s.rounds[0].status, RoundStatus.COMPLETED)
        s.set_mode('LEARN')
        self.assertIn(s.next_question().card_id, {c.id for c in s.cards[10:]})

    def test_review_mode_never_introduces_locked_cards_and_persists(self):
        s = self.make(20)
        s.set_mode('REVIEW')
        self.assertIsNone(s.next_question())
        s.set_mode('LEARN')
        self.finish_current_round(s)
        self.now += 10 ** 8
        s.set_mode('REVIEW')
        q = s.next_question()
        restored = self.round_trip(s)
        self.assertEqual(restored.mode, 'REVIEW')
        self.assertEqual(restored.next_question(), q)

    def test_empty_and_duplicate_decks(self):
        s = self.make(0)
        self.assertTrue(s.complete)
        self.assertIsNone(s.next_question())
        self.assertTrue(self.round_trip(s).complete)
        with self.assertRaises(ValueError):
            StudySession([('a', 'b'), ('a', 'b')])

    def test_invalid_mastery_configuration(self):
        for values in (dict(round_size=0), dict(minimum_successful_recalls=1), dict(minimum_active_recall_successes=0),
                       dict(minimum_spacing_questions=0), dict(weight_mastered=0), dict(incorrect_answer_penalty=1),
                       dict(allow_multiple_choice=1), dict(minimum_spacing=float('nan'))):
            with self.assertRaises(ValueError):
                StudyConfig(**values)


if __name__ == '__main__':
    unittest.main()
