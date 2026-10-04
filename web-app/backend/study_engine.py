"""Strict closed-round learning, followed by mixed global mastery.

Question spacing uses answered-question steps; timestamps are Unix seconds.
The memory scores are heuristics, not calibrated recall probabilities.
"""
from dataclasses import asdict, dataclass, field
from enum import Enum
import copy
import hashlib
import math
import random
import time


class State(str, Enum):
    NEW = 'NEW'
    UNSEEN = 'NEW'  # Compatibility name for callers of the former engine.
    UNTESTED = 'UNTESTED'
    LEARNING = 'LEARNING'
    FAMILIAR = 'FAMILIAR'
    MASTERED = 'MASTERED'


class RoundStatus(str, Enum):
    LOCKED = 'LOCKED'
    ACTIVE = 'ACTIVE'
    COMPLETED = 'COMPLETED'


class Phase(str, Enum):
    INITIAL_ROUND_LEARNING = 'INITIAL_ROUND_LEARNING'
    FINAL_MASTERY_ROUND = 'FINAL_MASTERY_ROUND'
    COMPLETE = 'COMPLETE'


@dataclass(frozen=True)
class StudyConfig:
    round_size: int = 10
    mastery_threshold: float = .85
    minimum_successful_recalls: int = 3
    minimum_active_recall_successes: int = 1
    minimum_spaced_recalls: int = 2
    minimum_spacing_questions: int = 3
    minimum_spacing: float = 300  # Time-based fallback for a one-card group.
    weight_new: float = 3
    weight_learning: float = 4
    weight_familiar: float = 2
    weight_mastered: float = .15
    incorrect_answer_penalty: float = .55
    familiar_after: int = 1
    reverse_after: int = 3
    allow_reverse_direction: bool = False
    allow_multiple_choice: bool = True
    allow_typed_recall: bool = False
    review_interval: float = 86400
    learning_interval: float = 30

    def __post_init__(self):
        for name in ('round_size', 'minimum_successful_recalls', 'minimum_active_recall_successes',
                     'minimum_spaced_recalls', 'minimum_spacing_questions', 'familiar_after', 'reverse_after'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f'{name} must be a positive integer')
        if self.minimum_successful_recalls < 2:
            raise ValueError('Mastery requires repeated successful recall')
        for name in ('minimum_spacing', 'review_interval', 'learning_interval',
                     'weight_new', 'weight_learning', 'weight_familiar', 'weight_mastered'):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be positive and finite')
        for name in ('mastery_threshold', 'incorrect_answer_penalty'):
            value = getattr(self, name)
            if type(value) not in (int, float) or not 0 < value < 1:
                raise ValueError(f'{name} must be between zero and one')
        for name in ('allow_reverse_direction', 'allow_multiple_choice', 'allow_typed_recall'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f'{name} must be a boolean')


@dataclass
class MasteryProgress:
    state: str = State.NEW
    attempts: int = 0
    correct_total: int = 0
    mistakes: int = 0
    consecutive_correct: int = 0
    spaced_recalls: int = 0
    active_recalls: int = 0
    mastery_score: float = .1
    recall_probability: float = .1
    history: list = field(default_factory=list)
    successful_directions: list = field(default_factory=list)
    last_reviewed: float | None = None
    last_success: float | None = None
    next_review: float = 0
    stability: float = 300
    last_seen_step: int = -1
    last_answer_step: int = -1
    questions_since_last_seen: int = 0

    @property
    def mastered(self):
        return self.state == State.MASTERED


@dataclass
class CardState(MasteryProgress):
    id: str = ''
    term: str = ''
    definition: str = ''
    round_id: int = 0
    final: MasteryProgress = field(default_factory=lambda: MasteryProgress(state=State.UNTESTED))
    review: MasteryProgress | None = None

    @property
    def initial_round_mastery(self):
        return self.state

    @property
    def final_round_mastery(self):
        return self.final.state


def card_id(term, definition):
    return hashlib.sha256((term + '\0' + definition).encode()).hexdigest()


@dataclass
class StudyRound:
    id: int | str
    card_ids: list
    status: str = RoundStatus.LOCKED
    introduced_ids: list = field(default_factory=list)


@dataclass(frozen=True)
class Question:
    card_id: str
    kind: str
    direction: str
    prompt: str
    answer: str
    options: tuple = ()


class MasteryEvaluator:
    def __init__(self, config):
        self.config = config

    def update(self, progress):
        cfg = self.config
        if (progress.mastery_score >= cfg.mastery_threshold
                and progress.consecutive_correct >= cfg.minimum_successful_recalls
                and progress.spaced_recalls >= cfg.minimum_spaced_recalls
                and progress.active_recalls >= cfg.minimum_active_recall_successes):
            progress.state = State.MASTERED
        elif progress.consecutive_correct >= cfg.familiar_after:
            progress.state = State.FAMILIAR
        else:
            progress.state = State.LEARNING


class MemoryModel:
    def __init__(self, config):
        self.config = config
        self.mastery = MasteryEvaluator(config)

    def probability(self, progress, now):
        elapsed = max(0, now - progress.last_reviewed) if progress.last_reviewed is not None else 0
        progress.recall_probability = max(.01, progress.mastery_score * math.exp(-elapsed / progress.stability))
        return progress.recall_probability

    def record(self, progress, correct, question, now, step, group_size, phase):
        cfg = self.config
        spacing = max(0, now - progress.last_reviewed) if progress.last_reviewed is not None else 0
        intervening = max(0, step - progress.last_answer_step - 1) if progress.last_answer_step >= 0 else 0
        # Small groups still require other cards; a singleton requires elapsed time.
        strong = progress.last_answer_step >= 0 and (
            intervening >= min(cfg.minimum_spacing_questions, group_size - 1)
            if group_size > 1 else spacing >= cfg.minimum_spacing)
        active = question.kind in ('free_recall', 'typed')
        progress.history.append(dict(correct=correct, timestamp=now, response_type=question.kind,
                                     difficulty={'multiple_choice': 1, 'free_recall': 2, 'typed': 3}[question.kind],
                                     direction=question.direction, spacing=spacing,
                                     intervening_questions=intervening, strong_recall=strong, phase=phase))
        progress.attempts += 1
        if correct:
            progress.correct_total += 1
            progress.consecutive_correct += 1
            progress.spaced_recalls += int(strong)
            # Correction repetitions do not contribute active mastery evidence.
            progress.active_recalls += int(active and strong)
            progress.last_success = now
            if question.direction not in progress.successful_directions:
                progress.successful_directions.append(question.direction)
            gain = .5 if strong and active else .22 if strong else .08 if active else .05
            progress.mastery_score += (1 - progress.mastery_score) * gain
            progress.stability = max(progress.stability, spacing) * (2 if strong else 1.1)
        else:
            progress.mistakes += 1
            progress.consecutive_correct = progress.spaced_recalls = progress.active_recalls = 0
            progress.mastery_score = max(.05, progress.mastery_score * (1 - cfg.incorrect_answer_penalty))
            progress.stability = max(cfg.learning_interval, progress.stability * .5)
        self.mastery.update(progress)
        progress.next_review = now + (max(cfg.review_interval, progress.stability)
                                      if progress.mastered else cfg.learning_interval)
        progress.last_reviewed = now
        progress.last_answer_step = step
        self.probability(progress, now)


class RoundManager:
    def __init__(self, cards, round_size):
        self.rounds = [StudyRound(index, [c.id for c in cards[start:start + round_size]])
                       for index, start in enumerate(range(0, len(cards), round_size))]
        for group in self.rounds:
            for card in cards[group.id * round_size:(group.id + 1) * round_size]:
                card.round_id = group.id
        self.current_round_index = 0
        self.final_round = StudyRound('final', [c.id for c in cards])
        self.phase = Phase.INITIAL_ROUND_LEARNING if cards else Phase.COMPLETE
        if self.rounds:
            self.rounds[0].status = RoundStatus.ACTIVE
        else:
            self.final_round.status = RoundStatus.COMPLETED

    @property
    def active_round(self):
        if self.phase == Phase.INITIAL_ROUND_LEARNING:
            return self.rounds[self.current_round_index]
        if self.phase == Phase.FINAL_MASTERY_ROUND:
            return self.final_round
        return None

    def complete_if_mastered(self, cards):
        group = self.active_round
        if group is None:
            return
        by_id = {c.id: c for c in cards}
        final = self.phase == Phase.FINAL_MASTERY_ROUND
        if not all((by_id[i].final if final else by_id[i]).mastered for i in group.card_ids):
            return
        group.status = RoundStatus.COMPLETED
        if final:
            self.phase = Phase.COMPLETE
        else:
            self.current_round_index += 1
            if self.current_round_index < len(self.rounds):
                self.rounds[self.current_round_index].status = RoundStatus.ACTIVE
            else:
                self.phase = Phase.FINAL_MASTERY_ROUND
                self.final_round.status = RoundStatus.ACTIVE
                # Keep all original learning evidence; start separate final evidence.
                for card in cards:
                    card.final = MasteryProgress(state=State.UNTESTED, stability=card.stability)


class StudyScheduler:
    """Receives only the allowed group. No deck or future-round fallback."""
    def __init__(self, config, rng, memory):
        self.config, self.rng, self.memory = config, rng, memory
        self.last_id = None
        self.recent_card_sequence = []

    def select(self, cards, now, step, phase=Phase.INITIAL_ROUND_LEARNING, introduced_ids=()):
        if not cards:
            return None
        final = phase == Phase.FINAL_MASTERY_ROUND
        progress = lambda c: c.final if final else c.review if phase == 'REVIEW' else c
        unintroduced = [c for c in cards if c.id not in introduced_ids]
        if unintroduced:
            candidates = unintroduced
            if final:
                previous = next((c for c in cards if c.id == self.last_id), None)
                mixed = [c for c in candidates if previous is None or c.round_id != previous.round_id]
                candidates = mixed or candidates
            else:
                candidates = unintroduced[:1]
        else:
            candidates = [c for c in cards if c.id != self.last_id] or cards
            gap = min(self.config.minimum_spacing_questions, len(cards) - 1)
            spaced = [c for c in candidates if progress(c).last_answer_step < 0
                      or step - progress(c).last_answer_step - 1 >= gap]
            candidates = spaced or candidates
        cfg = self.config
        state_weights = {State.NEW: cfg.weight_new, State.UNTESTED: cfg.weight_new,
                         State.LEARNING: cfg.weight_learning, State.FAMILIAR: cfg.weight_familiar,
                         State.MASTERED: cfg.weight_mastered}
        weights = []
        for card in candidates:
            evidence = progress(card)
            recall = self.memory.probability(evidence, now)
            if final and evidence.state == State.UNTESTED:
                recall = self.memory.probability(card, now)
            distance = max(1, step - evidence.last_seen_step)
            weights.append(state_weights[evidence.state] * (.1 + (1 - recall) ** 2) * min(distance, 10))
        card = self.rng.choices(candidates, weights=weights, k=1)[0]
        self.last_id = card.id
        self.recent_card_sequence = (self.recent_card_sequence + [card.id])[-20:]
        progress(card).last_seen_step = step
        return card


class QuestionGenerator:
    def __init__(self, config, rng):
        self.config, self.rng = config, rng

    def select(self, card, allowed_cards, phase=Phase.INITIAL_ROUND_LEARNING):
        if card.id not in {c.id for c in allowed_cards}:
            raise ValueError('Question card is outside the allowed group')
        evidence = card.final if phase == Phase.FINAL_MASTERY_ROUND else card.review if phase == 'REVIEW' else card
        # Original performance guides final difficulty without counting as final mastery.
        difficulty = card if phase == Phase.FINAL_MASTERY_ROUND and evidence.state == State.UNTESTED else evidence
        previous_direction = evidence.history[-1]['direction'] if evidence.history else 'forward'
        reverse = (self.config.allow_reverse_direction and difficulty.consecutive_correct >= self.config.reverse_after
                   and previous_direction == 'forward')
        direction = 'reverse' if reverse else 'forward'
        prompt, answer = (card.definition, card.term) if reverse else (card.term, card.definition)
        recognition = self.config.allow_multiple_choice and difficulty.state in (State.NEW, State.LEARNING)
        if recognition:
            answers = list(dict.fromkeys(c.term if reverse else c.definition for c in allowed_cards if c.id != card.id))
            answers = [value for value in answers if value != answer]
            if answers:
                options = self.rng.sample(answers, min(3, len(answers))) + [answer]
                self.rng.shuffle(options)
                return Question(card.id, 'multiple_choice', direction, prompt, answer, tuple(options))
        kind = 'typed' if self.config.allow_typed_recall else 'free_recall'
        return Question(card.id, kind, direction, prompt, answer)


QuestionSelector = QuestionGenerator


class StudySession:
    VERSION = 3

    def __init__(self, raw_cards, config=None, rng=None, clock=None):
        self.config = config or StudyConfig()
        self.rng, self.clock = rng or random.Random(), clock or time.time
        self.cards = [CardState(id=card_id(t, d), term=t, definition=d) for t, d in raw_cards]
        if len({c.id for c in self.cards}) != len(self.cards):
            raise ValueError('Duplicate cards in deck')
        self.round_manager = RoundManager(self.cards, self.config.round_size)
        self.study_set_id = hashlib.sha256(''.join(sorted(c.id for c in self.cards)).encode()).hexdigest()
        self.memory = MemoryModel(self.config)
        self.scheduler = StudyScheduler(self.config, self.rng, self.memory)
        self.review_scheduler = StudyScheduler(self.config, self.rng, self.memory)
        self.questions = QuestionGenerator(self.config, self.rng)
        self.step = self.session_correct = self.session_wrong = self.streak = 0
        self.current_question = None
        self.mode = 'LEARN'

    @property
    def phase(self):
        return self.round_manager.phase

    @property
    def rounds(self):
        return self.round_manager.rounds

    @property
    def active_round(self):
        return self.round_manager.active_round

    @property
    def current_round_index(self):
        return self.round_manager.current_round_index

    @property
    def complete(self):
        return self.phase == Phase.COMPLETE

    @property
    def active_pool(self):
        group = self.active_round
        by_id = {c.id: c for c in self.cards}
        return [by_id[i] for i in group.card_ids] if group else []

    def progress_for(self, card):
        return card.review if self.mode == 'REVIEW' else card.final if self.phase == Phase.FINAL_MASTERY_ROUND else card

    @property
    def mastered_count(self):
        return sum(c.final.mastered for c in self.cards) if self.phase != Phase.INITIAL_ROUND_LEARNING else sum(c.mastered for c in self.cards)

    @property
    def total(self):
        return len(self.cards)

    @property
    def round_mastered_count(self):
        if self.mode == 'REVIEW':
            return sum(c.review.mastered for c in self.cards if c.review is not None)
        return sum(self.progress_for(c).mastered for c in self.active_pool)

    def _review_cards(self, now):
        completed_ids = {i for group in self.rounds if group.status == RoundStatus.COMPLETED for i in group.card_ids}
        return [c for c in self.cards if c.id in completed_ids and c.review is not None and c.review.next_review <= now]

    @property
    def due_review_count(self):
        return len(self._review_cards(self.clock()))

    def set_mode(self, mode):
        if mode not in ('LEARN', 'REVIEW'):
            raise ValueError('Unknown study mode')
        if mode != self.mode:
            # An explicit mode change abandons the unanswered prompt without grading it.
            self.current_question = None
        self.mode = mode
        if mode == 'REVIEW':
            for card in self.cards:
                if self.rounds[card.round_id].status == RoundStatus.COMPLETED and card.review is None:
                    data = {name: getattr(card, name) for name in MasteryProgress.__dataclass_fields__}
                    # Review evidence is separate from both mastery phases.
                    card.review = MasteryProgress(**copy.deepcopy(data))

    def configure(self, config):
        """Apply settings without discarding answers or completed learning evidence."""
        old_phase = self.phase
        ordered = {c.id: c for c in self.cards}
        ordered_cards = [ordered[i] for r in self.rounds for i in r.card_ids]
        self.config = config
        self.memory.config = self.memory.mastery.config = config
        self.scheduler.config = self.review_scheduler.config = self.questions.config = config
        # Completed initial groups remain acquired; the active phase uses the new criteria.
        evidence = self.active_pool if old_phase == Phase.INITIAL_ROUND_LEARNING else [c.final for c in self.cards]
        for progress in evidence:
            if progress.attempts:
                self.memory.mastery.update(progress)
        manager = RoundManager(ordered_cards, config.round_size)
        for group in manager.rounds:
            if all(ordered[i].mastered for i in group.card_ids):
                group.status = RoundStatus.COMPLETED
                group.introduced_ids = list(group.card_ids)
                manager.current_round_index += 1
            else:
                group.status = RoundStatus.ACTIVE
                group.introduced_ids = [i for i in group.card_ids if ordered[i].attempts]
                break
        if manager.current_round_index == len(manager.rounds):
            manager.phase = Phase.FINAL_MASTERY_ROUND
            manager.final_round.status = RoundStatus.ACTIVE
            if old_phase == Phase.INITIAL_ROUND_LEARNING:
                for card in self.cards:
                    card.final = MasteryProgress(state=State.UNTESTED, stability=card.stability)
            manager.final_round.introduced_ids = [c.id for c in ordered_cards if c.final.attempts]
            if all(c.final.mastered for c in self.cards):
                manager.phase = Phase.COMPLETE
                manager.final_round.status = RoundStatus.COMPLETED
        self.round_manager = manager
        # A prompt may now belong to another group or use a different response mode.
        self.current_question = None

    def _allowed_cards(self, now):
        return self._review_cards(now) if self.mode == 'REVIEW' else self.active_pool

    def next_question(self):
        if self.current_question:
            self._validate_question(self.current_question, self._allowed_cards(self.clock()))
            return self.current_question
        now = self.clock()
        cards = self._allowed_cards(now)
        scheduler = self.review_scheduler if self.mode == 'REVIEW' else self.scheduler
        phase = 'REVIEW' if self.mode == 'REVIEW' else self.phase
        introduced = [c.id for c in cards] if self.mode == 'REVIEW' else self.active_round.introduced_ids if self.active_round else []
        card = scheduler.select(cards, now, self.step, phase, introduced)
        if card is None:
            return None
        if self.mode == 'LEARN' and card.id not in introduced:
            self.active_round.introduced_ids.append(card.id)
        evidence = self.progress_for(card)
        if evidence.state in (State.NEW, State.UNTESTED):
            # Generate using the pre-introduction difficulty, then mark as introduced.
            self.current_question = self.questions.select(card, cards, phase)
            evidence.state = State.LEARNING
        else:
            self.current_question = self.questions.select(card, cards, phase)
        return self.current_question

    @staticmethod
    def _validate_question(question, allowed_cards):
        card = next((c for c in allowed_cards if c.id == question.card_id), None)
        if card is None:
            raise ValueError('Question is outside the allowed group')
        if question.kind not in ('multiple_choice', 'free_recall', 'typed') or question.direction not in ('forward', 'reverse'):
            raise ValueError('Invalid question format')
        prompt, answer = (card.definition, card.term) if question.direction == 'reverse' else (card.term, card.definition)
        if question.prompt != prompt or question.answer != answer:
            raise ValueError('Question does not match card')
        if not isinstance(question.options, (tuple, list)) or any(not isinstance(o, str) for o in question.options):
            raise ValueError('Invalid answer choices')
        if question.kind == 'multiple_choice':
            allowed_answers = {c.term if question.direction == 'reverse' else c.definition for c in allowed_cards}
            if (len(question.options) < 2 or answer not in question.options
                    or len(set(question.options)) != len(question.options)
                    or not set(question.options) <= allowed_answers):
                raise ValueError('Answer choices are outside the allowed group')
        elif question.options:
            raise ValueError('Recall questions cannot contain answer choices')
        return card

    def grade(self, correct):
        if type(correct) is not bool or self.current_question is None:
            raise ValueError('An unanswered question and boolean grade are required')
        now = self.clock()
        card = self._validate_question(self.current_question, self._allowed_cards(now))
        self.memory.record(self.progress_for(card), correct, self.current_question, now, self.step,
                           len(self.active_pool) if self.mode == 'LEARN' else len(self.cards),
                           self.phase if self.mode == 'LEARN' else 'REVIEW')
        self.step += 1
        for item in self.cards:
            for evidence in (item, item.final, item.review):
                if evidence is not None and evidence.last_seen_step >= 0:
                    evidence.questions_since_last_seen = max(0, self.step - evidence.last_seen_step - 1)
        self.session_correct += int(correct)
        self.session_wrong += int(not correct)
        self.streak = self.streak + 1 if correct else 0
        self.current_question = None
        if self.mode == 'LEARN':
            self.round_manager.complete_if_mastered(self.cards)

    def to_dict(self):
        def metadata(scheduler):
            return dict(last_id=scheduler.last_id, recent_card_sequence=list(scheduler.recent_card_sequence))
        return dict(version=self.VERSION, study_set_id=self.study_set_id, config=asdict(self.config),
                    cards=[asdict(c) for c in self.cards], rounds=[asdict(r) for r in self.rounds],
                    final_round=asdict(self.round_manager.final_round), phase=self.phase,
                    current_round_index=self.current_round_index, mode=self.mode,
                    step=self.step, session_correct=self.session_correct, session_wrong=self.session_wrong,
                    streak=self.streak, current_question=asdict(self.current_question) if self.current_question else None,
                    scheduler=metadata(self.scheduler), review_scheduler=metadata(self.review_scheduler),
                    random_state=self.rng.getstate())

    def restore(self, data):
        """Validate in a temporary session so a failed load never partially mutates progress."""
        candidate = StudySession([(c.term, c.definition) for c in self.cards], self.config,
                                 random.Random(), self.clock)
        candidate._restore(data)
        self.__dict__.update(candidate.__dict__)

    @staticmethod
    def _validate_progress(evidence, final=False):
        allowed_states = (State.UNTESTED, State.LEARNING, State.FAMILIAR, State.MASTERED) if final else (State.NEW, State.LEARNING, State.FAMILIAR, State.MASTERED)
        if evidence.state not in allowed_states:
            raise ValueError('Invalid learning state')
        for name in ('attempts', 'correct_total', 'mistakes', 'consecutive_correct', 'spaced_recalls',
                     'active_recalls', 'questions_since_last_seen'):
            value = getattr(evidence, name)
            if type(value) is not int or value < 0:
                raise ValueError('Invalid card counts')
        if (evidence.attempts != evidence.correct_total + evidence.mistakes
                or evidence.consecutive_correct > evidence.correct_total
                or evidence.spaced_recalls > evidence.correct_total or evidence.active_recalls > evidence.correct_total):
            raise ValueError('Inconsistent answer counts')
        for name in ('last_seen_step', 'last_answer_step'):
            if type(getattr(evidence, name)) is not int or getattr(evidence, name) < -1:
                raise ValueError('Invalid question step')
        for name in ('mastery_score', 'recall_probability'):
            value = getattr(evidence, name)
            if type(value) not in (int, float) or not 0 <= value <= 1:
                raise ValueError('Invalid probability')
        for name in ('last_reviewed', 'last_success', 'next_review', 'stability'):
            value = getattr(evidence, name)
            if value is None and name in ('last_reviewed', 'last_success'):
                continue
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError('Invalid timestamp or interval')
        if evidence.stability <= 0:
            raise ValueError('Invalid memory stability')
        if not isinstance(evidence.history, list) or not isinstance(evidence.successful_directions, list):
            raise ValueError('Invalid history')
        if any(d not in ('forward', 'reverse') for d in evidence.successful_directions):
            raise ValueError('Invalid direction')
        for event in evidence.history:
            if (not isinstance(event, dict) or type(event.get('correct')) is not bool
                    or event.get('response_type') not in ('multiple_choice', 'free_recall', 'typed')
                    or event.get('direction') not in ('forward', 'reverse')):
                raise ValueError('Invalid answer history')
            for name in ('timestamp', 'spacing', 'difficulty'):
                value = event.get(name)
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError('Invalid answer evidence')
            if 'intervening_questions' in event and (type(event['intervening_questions']) is not int or event['intervening_questions'] < 0):
                raise ValueError('Invalid question spacing')
            if 'strong_recall' in event and type(event['strong_recall']) is not bool:
                raise ValueError('Invalid recall evidence')

    def _restore(self, data):
        version = data.get('version')
        if version not in (1, 2, self.VERSION):
            raise ValueError('Unknown progress version')
        if version == self.VERSION:
            self.config = StudyConfig(**data['config'])
            self.memory = MemoryModel(self.config)
            self.scheduler = StudyScheduler(self.config, self.rng, self.memory)
            self.review_scheduler = StudyScheduler(self.config, self.rng, self.memory)
            self.questions = QuestionGenerator(self.config, self.rng)
        saved = {}
        for item in data['cards']:
            if version == 1:
                card = CardState(id=card_id(item['term'], item['definition']), term=item['term'], definition=item['definition'])
                card.correct_total, card.mistakes = item['correct_total'], item['mistakes']
                card.attempts = card.correct_total + card.mistakes
                card.state = State.FAMILIAR if card.correct_total else State.LEARNING if card.attempts else State.NEW
            elif version == 2:
                values = dict(item)
                values['state'] = {'UNSEEN': State.NEW, 'REVIEW': State.MASTERED}.get(values['state'], values['state'])
                values['last_seen_step'] = max(-1, values['last_seen_step'])
                card = CardState(**values)
                # Historical time-spaced evidence remains; old step evidence is unknown.
            else:
                values = dict(item)
                values['final'] = MasteryProgress(**values['final'])
                values['review'] = MasteryProgress(**values['review']) if values['review'] is not None else None
                card = CardState(**values)
            if not isinstance(card.term, str) or not isinstance(card.definition, str) or card.id != card_id(card.term, card.definition):
                raise ValueError('Invalid card identity')
            self._validate_progress(card)
            self._validate_progress(card.final, final=True)
            if card.review is not None:
                self._validate_progress(card.review)
            if card.id in saved:
                raise ValueError('Duplicate saved card')
            saved[card.id] = card
        if version == self.VERSION and (set(saved) != {c.id for c in self.cards} or data['study_set_id'] != self.study_set_id):
            raise ValueError('The deck changed; reset learning to create new rounds')
        self.cards = [saved.get(c.id, c) for c in self.cards]
        for name in ('step', 'session_correct', 'session_wrong', 'streak'):
            value = data[name]
            if type(value) is not int or value < 0:
                raise ValueError('Invalid session count')
            setattr(self, name, value)
        if self.step != self.session_correct + self.session_wrong or self.streak > self.session_correct:
            raise ValueError('Inconsistent session counts')
        self.round_manager = RoundManager(self.cards, self.config.round_size)
        if version == self.VERSION:
            self.round_manager.rounds = [StudyRound(**r) for r in data['rounds']]
            self.round_manager.final_round = StudyRound(**data['final_round'])
            self.round_manager.phase = Phase(data['phase'])
            self.round_manager.current_round_index = data['current_round_index']
            self.mode = data['mode']
            self._validate_rounds()
            self._restore_scheduler(self.scheduler, data['scheduler'])
            self._restore_scheduler(self.review_scheduler, data['review_scheduler'])
            def tuples(value):
                return tuple(tuples(v) for v in value) if isinstance(value, list) else value
            self.rng.setstate(tuples(data['random_state']))
        else:
            # Convert the moving pool into fixed groups, preserving every card's history.
            while self.active_round is not None and self.phase == Phase.INITIAL_ROUND_LEARNING:
                if not all(c.mastered for c in self.active_pool):
                    break
                self.round_manager.complete_if_mastered(self.cards)
            if self.phase == Phase.INITIAL_ROUND_LEARNING:
                self.active_round.introduced_ids = [c.id for c in self.active_pool if c.attempts]
        pending = data.get('current_question')
        if pending:
            values = dict(pending)
            values['options'] = tuple(values.get('options', ()))
            question = Question(**values)
            if version != self.VERSION:
                card = next((c for c in self.active_pool if c.id == question.card_id), None)
                # Discard old pending questions outside the newly closed round.
                question = Question(card.id, 'free_recall', 'forward', card.term, card.definition) if card else None
            if question:
                self._validate_question(question, self._allowed_cards(self.clock()))
                if self.mode == 'LEARN' and question.card_id not in self.active_round.introduced_ids:
                    self.active_round.introduced_ids.append(question.card_id)
                self.current_question = question

    def _restore_scheduler(self, scheduler, metadata):
        ids = {c.id for c in self.cards}
        if metadata['last_id'] is not None and metadata['last_id'] not in ids:
            raise ValueError('Invalid scheduler card')
        recent = metadata['recent_card_sequence']
        if not isinstance(recent, list) or len(recent) > 20 or any(i not in ids for i in recent):
            raise ValueError('Invalid recent sequence')
        scheduler.last_id = metadata['last_id']
        scheduler.recent_card_sequence = list(recent)

    def _validate_rounds(self):
        rounds = self.rounds
        ids = [c.id for c in self.cards]
        assigned = []
        for index, group in enumerate(rounds):
            if type(group.id) is not int or group.id != index or not isinstance(group.card_ids, list) or not group.card_ids:
                raise ValueError('Invalid round assignment')
            if len(group.card_ids) != min(self.config.round_size, len(ids) - len(assigned)):
                raise ValueError('Invalid round size')
            assigned.extend(group.card_ids)
        if len(assigned) != len(ids) or set(assigned) != set(ids):
            raise ValueError('Each card must belong to exactly one round')
        final = self.round_manager.final_round
        if final.id != 'final' or final.card_ids != assigned:
            raise ValueError('Final round must contain the complete set')
        by_id = {c.id: c for c in self.cards}
        for group in rounds + [final]:
            if (group.status not in tuple(RoundStatus) or not isinstance(group.introduced_ids, list)
                    or len(set(group.introduced_ids)) != len(group.introduced_ids)
                    or not set(group.introduced_ids) <= set(group.card_ids)):
                raise ValueError('Invalid round state')
            if group.status == RoundStatus.LOCKED and group.introduced_ids:
                raise ValueError('Locked rounds cannot introduce cards')
        for group in rounds:
            for i in group.card_ids:
                # RoundManager built from current deck order; restore saved assignments.
                by_id[i].round_id = group.id
            if group.status == RoundStatus.COMPLETED and not all(by_id[i].mastered for i in group.card_ids):
                raise ValueError('Completed rounds require all cards mastered')
        index = self.current_round_index
        if type(index) is not int or not 0 <= index <= len(rounds) or self.mode not in ('LEARN', 'REVIEW'):
            raise ValueError('Invalid study position')
        if self.phase == Phase.INITIAL_ROUND_LEARNING:
            if index == len(rounds) or final.status != RoundStatus.LOCKED:
                raise ValueError('Invalid active round')
            expected = [RoundStatus.COMPLETED] * index + [RoundStatus.ACTIVE] + [RoundStatus.LOCKED] * (len(rounds) - index - 1)
            if [r.status for r in rounds] != expected:
                raise ValueError('Only the first unfinished round may be active')
            if any(c.final.state != State.UNTESTED or c.final.attempts for c in self.cards):
                raise ValueError('Final mastery cannot start before initial rounds complete')
        else:
            if index != len(rounds) or any(r.status != RoundStatus.COMPLETED for r in rounds):
                raise ValueError('All normal rounds must complete before final mastery')
            expected = RoundStatus.ACTIVE if self.phase == Phase.FINAL_MASTERY_ROUND else RoundStatus.COMPLETED
            if final.status != expected:
                raise ValueError('Invalid final mastery status')
            if self.complete and not all(c.final.mastered for c in self.cards):
                raise ValueError('Completion requires every card mastered again')
