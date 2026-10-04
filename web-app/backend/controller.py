"""Browser interactions and persisted learning preferences."""
import copy
import json
import os
import secrets
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .study_engine import Phase, Question, RoundStatus, StudyConfig, StudySession

DATA_DIR = Path(__file__).resolve().parent / "data"
LEGACY_PATH = Path(__file__).resolve().parents[2] / "flashcard_progress.json"
DEFAULT_CONFIG = replace(StudyConfig(), allow_multiple_choice=False, allow_reverse_direction=False)


class InvalidAction(ValueError):
    pass


@dataclass
class CardView:
    question: Question
    showing_answer: bool = False
    answered: bool = False
    correct: bool | None = None
    typed_response: str = ""


class WebStudy:
    def __init__(self, progress_path, legacy_path=LEGACY_PATH, raw_cards=None, config=None):
        self.path = Path(progress_path)
        self.raw_cards = raw_cards if raw_cards is not None else json.loads(
            (DATA_DIR / "flashcards.json").read_text(encoding="utf-8")
        )
        self.session = StudySession(self.raw_cards, replace(config or DEFAULT_CONFIG,
                                                           allow_multiple_choice=False, allow_reverse_direction=False))
        self.history = []
        self.index = -1
        self.context = None
        self.notice = ""
        self.revision = secrets.token_hex(16)
        source = self.path if self.path.exists() else Path(legacy_path) if legacy_path else None
        if source is not None and source.exists():
            # Read the desktop save once. All subsequent writes target the web save.
            data = json.loads(source.read_text(encoding="utf-8"))
            if data.get("version") == StudySession.VERSION and not data.get("web_settings_version"):
                # Desktop imports and older web saves used the fixed flashcard modes.
                data["config"]["allow_multiple_choice"] = False
                data["config"]["allow_reverse_direction"] = False
            self.session.restore(data)
            if self.session.mode == "REVIEW":
                self.session.set_mode("LEARN")
        self.load_next()
        self.save()

    def navigation_context(self):
        return self.session.mode, self.session.phase, self.session.current_round_index

    @property
    def view(self):
        return self.history[self.index] if self.index >= 0 else None

    @property
    def historical(self):
        return self.index < len(self.history) - 1

    def load_next(self):
        context = self.navigation_context()
        if context != self.context:
            self.history, self.index, self.context = [], -1, context
        question = self.session.next_question()
        if question is not None and question.kind == "multiple_choice" and not self.session.config.allow_multiple_choice:
            question = replace(question, kind="free_recall", options=())
            self.session.current_question = question
        if question is not None and question.direction == "reverse" and not self.session.config.allow_reverse_direction:
            question = replace(question, direction="forward", prompt=question.answer, answer=question.prompt)
            self.session.current_question = question
        if question is None:
            # No pending question: review queue empty or learning completed.
            self.index = -1
            self.history = []
        else:
            if not self.history or self.history[-1].question != question or self.history[-1].answered:
                self.history.append(CardView(question))
            self.index = len(self.history) - 1

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".progress-",
                                             dir=self.path.parent, delete=False) as file:
                temporary = Path(file.name)
                json.dump({**self.session.to_dict(), "web_settings_version": 1}, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def record(self, correct):
        old_phase = self.session.phase
        self.session.grade(correct)
        self.view.answered, self.view.correct, self.view.showing_answer = True, correct, True
        self.notice = ""
        if self.session.mode == "LEARN" and old_phase != self.session.phase:
            self.notice = ("Tous les groupes sont maîtrisés. Place à la maîtrise finale !"
                           if self.session.phase == Phase.FINAL_MASTERY_ROUND
                           else "Bravo, tu as maîtrisé toutes les cartes une seconde fois !")

    def navigate(self, direction, response=None):
        if self.view is None:
            raise InvalidAction("Aucune carte à parcourir.")
        if response is not None and not self.view.answered and not self.historical:
            self.view.typed_response = response
        if direction == -1:
            if self.index > 0 and self.context == self.navigation_context():
                self.index -= 1
        elif direction == 1:
            if self.index + 1 < len(self.history):
                self.index += 1
            else:
                # Navigation never grades a skipped prompt.
                self.session.current_question = None
                self.load_next()
        else:
            raise InvalidAction("Direction invalide.")

    def apply(self, action):
        """Rollback in-memory state if saving fails, so retry cannot double-grade."""
        previous = copy.deepcopy(self.__dict__)
        try:
            self._apply(action)
            self.revision = secrets.token_hex(16)
            self.save()
        except Exception:
            self.__dict__.clear()
            self.__dict__.update(previous)
            raise
        return self.snapshot()

    def _apply(self, action):
        kind, view = action.type, self.view
        if kind == "flip":
            if view is None:
                raise InvalidAction("Aucune carte à retourner.")
            if not view.answered and not self.historical and view.question.kind != "free_recall":
                view.question = replace(view.question, kind="free_recall", options=())
                self.session.current_question = view.question
            view.showing_answer = not view.showing_answer
        elif kind == "grade":
            if (view is None or not view.showing_answer or view.answered or self.historical
                    or view.question.kind != "free_recall" or type(action.correct) is not bool):
                raise InvalidAction("Révèle la réponse de la carte actuelle avant de l’évaluer.")
            self.record(action.correct)
            self.navigate(1)
        elif kind == "navigate":
            self.navigate(action.direction, action.response)
        elif kind == "typed":
            if view is None or view.answered or self.historical or view.question.kind != "typed":
                raise InvalidAction("Cette carte n’attend pas de réponse écrite.")
            response = " ".join((action.response or "").casefold().split())
            if not response:
                raise InvalidAction("Écris une réponse avant de la vérifier.")
            view.typed_response = action.response
            self.record(response == " ".join(view.question.answer.casefold().split()))
        elif kind == "choice":
            if (view is None or view.answered or self.historical or view.question.kind != "multiple_choice"
                    or type(action.choice) is not int or not 0 <= action.choice < len(view.question.options)):
                raise InvalidAction("Choisis une réponse de la carte actuelle.")
            self.record(view.question.options[action.choice] == view.question.answer)
        elif kind == "mode":
            if action.mode != "LEARN":
                raise InvalidAction("Mode inconnu.")
            if action.mode != self.session.mode:
                self.session.set_mode(action.mode)
                self.notice = ""
                self.load_next()
        elif kind == "settings":
            if action.defaults:
                config = DEFAULT_CONFIG
            elif action.config is not None:
                try:
                    config = replace(self.session.config, **action.config)
                except (ValueError, TypeError) as error:
                    raise InvalidAction("Paramètres invalides. Vérifie les nombres et les limites indiquées.") from error
            elif type(action.typed) is bool:
                # Compatibility with existing clients that change only written recall.
                config = replace(self.session.config, allow_typed_recall=action.typed)
                self.session.config = config
                self.session.questions.config = self.session.memory.config = config
                self.session.memory.mastery.config = config
                self.session.scheduler.config = self.session.review_scheduler.config = config
                if self.history and not self.history[-1].answered:
                    pending = self.history[-1]
                    pending.question = replace(pending.question, kind="typed" if action.typed else "free_recall", options=())
                    pending.showing_answer = False
                    self.session.current_question = pending.question
                return
            else:
                raise InvalidAction("Choisis les paramètres à enregistrer.")
            if config != self.session.config:
                self.session.configure(config)
                self.history, self.index, self.context = [], -1, None
                self.notice = "Paramètres d’apprentissage enregistrés. Tes réponses sont conservées."
                self.load_next()
        elif kind == "reset":
            self.session = StudySession(self.raw_cards, self.session.config)
            self.history, self.index, self.context = [], -1, None
            self.notice = "Une nouvelle session commence. À ton rythme."
            self.load_next()
        elif kind == "refresh":
            if self.session.mode == "REVIEW" and view is None:
                self.load_next()

    def snapshot(self):
        s, view = self.session, self.view
        by_id = {c.id: c for c in s.cards}
        initial = sum(c.mastered for c in s.cards)
        final = sum(c.final.mastered for c in s.cards)
        completed = {r.id for r in s.rounds if r.status == RoundStatus.COMPLETED}
        review_evidence = [c.review if c.review is not None else c for c in s.cards if c.round_id in completed]
        now = s.clock()
        next_dates = [c.next_review for c in review_evidence if c.next_review > now]
        current = None
        if view is not None:
            card = by_id[view.question.card_id]
            evidence = s.progress_for(card) or card
            current = dict(
                card_id=card.id, kind=view.question.kind, direction=view.question.direction,
                options=list(view.question.options),
                text=view.question.answer if view.showing_answer else view.question.prompt,
                showing_answer=view.showing_answer, answered=view.answered, correct=view.correct,
                historical=self.historical, typed_response=view.typed_response,
                can_grade=view.showing_answer and not view.answered and not self.historical,
                can_previous=self.index > 0 and self.context == self.navigation_context(),
                position=self.index + 1, history_length=len(self.history),
                state=evidence.state, score=evidence.mastery_score,
            )
        return dict(
            revision=self.revision, mode=s.mode, phase=s.phase, total=s.total,
            initial_mastered=initial, final_mastered=final,
            progress=(initial + final) / (2 * s.total) if s.total else 1,
            active_round_index=s.current_round_index,
            active_mastered=final if s.complete and s.mode == "LEARN" else s.round_mastered_count,
            active_total=s.total if s.complete and s.mode == "LEARN" else len(s.active_pool), complete=s.complete,
            correct=s.session_correct, wrong=s.session_wrong, streak=s.streak,
            review_available=bool(completed),
            due_reviews=sum(c.next_review <= now for c in review_evidence),
            next_review_at=min(next_dates) if next_dates else None,
            typed_recall=s.config.allow_typed_recall,
            config=asdict(s.config), default_config=asdict(DEFAULT_CONFIG),
            round_size=s.config.round_size, notice=self.notice, question=current,
            rounds=[dict(id=r.id, status=r.status, total=len(r.card_ids),
                         mastered=sum(by_id[i].mastered for i in r.card_ids)) for r in s.rounds],
            final_status=s.round_manager.final_round.status,
            active_cards=[dict(id=c.id, term=c.term, state=(s.progress_for(c) or c).state,
                               score=(s.progress_for(c) or c).mastery_score) for c in s.active_pool],
        )
