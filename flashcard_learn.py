import json
import os
import tempfile
import tkinter as tk
from dataclasses import dataclass, replace
from pathlib import Path
from tkinter import messagebox

PROGRESS_PATH = Path(__file__).resolve().with_name("flashcard_progress.json")

# ============================================================
# Cartes codées en dur
# ============================================================

FLASHCARDS = [
    (
        "quoi une norme?",
        """- Indique ce qu'on doit faire ou ne pas faire.

- Son existence sert à s'assurer qu'une valeur est réalisé. Elle protège/favorise quelque chose qu'on considère important.

- Implique la possibilité d'une sanction

- Appartient à un système normatif."""
    ),
    (
        "Énoncé normatif :",
        "Prescrit ou interdit un comportement"
    ),
    (
        "Lettre de la norme vs L'esprit de la norme",
        """La lettre de la norme : ce que la règle dit concrètement, son énoncé.

L'esprit de la norme : la valeur que la règle cherche à réalisé

Exemple:

Vitesse max 100km/h

Lettre: roule < 100km/h
Esprit : protéger la sécuriter"""
    ),
    (
        "Les 4 systèmes normatif",
        "Déontologie, droit, moeurs, morale"
    ),
    (
        "Système normatif Déontologie",
        """S'applique dans une organisation d'une profession précise.
(Ex: code déontologie des ingénieurs)

- Règle propre à l'organisation
- Applicables aux personnes qui en font partie
- Basée sur des valeurs communes et pratiques professionnelles
- Sanctions formelles"""
    ),
    (
        "Système normatif Droit",
        """Les lois et règlements officielles d'une autorité politique.

Peut recevoir une sanction légale si on ne respecte pas la règle."""
    ),
    (
        "Système normatif Moeurs",
        """Une normes sociales informelles.

Maintenus par la pression sociale et existe parce qu'un groupe social considère certains comportement comme acceptable ou innaceptable.

Sanctions informelles comme exclusion ou désapprobation.

Légale, socialement mal vue."""
    ),
    (
        "Système normatif Morale",
        """Un système de croyances concernant le bien et le mal.

Deux personnes peuvent avoir des conceptions morale différentes.

Les sanctions sont surtout intérieur, et l'adhésion n'est pas toujours forte."""
    ),
    (
        "Flou normatif",
        """Lorsqu'on est dans une situation ou est-ce que les normes ne permettent pas de savoir clairement quoi faire.

On a situation à régler, mais les règles sont :
- Absente
- Vielle / dépassés
- Inéficace
- Inapplicable
- Non consensuelles
- Contradictoire"""
    ),
    (
        "3 causes princiaples du flou normatif",
        """1. Pas encore de norme adapté
2. Lettre de la nrome ne respecte plus son esprit
3. Deux normes entrent en conflit"""
    ),
    (
        "Les 4 valeurs de la profession d'ingénieur",
        """1. La compétence : doit avoir les connaissance et capacité de bien faire son travail

2. Sens de l'éthique : penser aux conséquences et le sens de son travail.

3. Responsabilité : Répondre et assumé ses choix et ses actes

4. Engagement sociale : Agit comme un citoyen responsable, tient compte de chose comme les développement durable, pense à la société."""
    ),
    (
        "C'est quoi le corporatisme",
        """Dans un modèle corporatiste, la corporation professionnelle cherche surtout à :

- Protéger ses membres
- Protéger la réputation de la profession contre les imposteurs.

Elle veut surtout protéger la profession elle-même et ses membres"""
    ),
    (
        "C'est quoi le système des ordre de profession",
        "Le but principale est de protégé le publique."
    ),
    (
        "Pourquoi certaines professions sont encadrées par un ordre professionnel",
        """On crée un ordre, lorsque le publique pourrait être vulnérable face à une profession spécialisée et que les conséquences d'un mauvais service peuvent être importante.

Critère:
- Un savoir très spécialiser est requis pour faire la profession
- Le public a de la difficulté à juger la qualité du service
- Les risques et les préjudices possibles sont importants.
- Le professionnel possède beaucoup d'autonomie et de responsabilité
- La relation peut être personnelle ou confidentielle"""
    ),
    (
        "Les constituantes de l'OIQ",
        "Présidence et direction générale, conseil d'administration, comité d'inspection profesionnelle, bureau du syndic, comité d'admission, conseil de discipline"
    ),
    (
        "Comité d'inspection professionnelle (CIP)",
        """Surveille la compétence et la pratique. S'assure que les ingénieurs restent compétents et que leur pratique est conforme.

Peut faire des inspections aléatoires sans plainte, mais prévient à l'avance"""
    ),
    (
        "Bureau du syndic",
        """Si on soupçonne qu'un ingénieur à manquer d'intégrité, diligence, néglicence, enfrait le code de déontologie, ect.

Le bureau du syndic va venir enquêter. Ce n'est pas aléatoire, il faut une plainte valable."""
    ),
    (
        "Conseil de discipline",
        """Sanctionne un geste illégale.

De l'amande à la radiation permanente."""
    ),
    (
        "Conseil d'administration",
        "Autorégulation. Établie des règles, pratiques et mécanisme qui protège le publique."
    ),
    (
        "Comité d'admission",
        "Contrôle l'admisssion à la profession"
    ),
    (
        "Présidence et direction générale",
        "Dirige"
    ),
    (
        "Responsabilité de l'ingénieur face au publique",
        """Doit tenir compte de:
- Vie
- Santé
- Propriété
- Environnement

Public = priorité principale"""
    ),
    (
        "Responsabilité de l'ingénieur face au client ou l'employeur",
        """Face au sens du Code, le patron est aussi considéré comme notre client.

On doit tenir compte les intérêt du client : agir avec compétence, intégrité, diligence, ect.

On n'obéit pas aveuglément, on conserve son indépendance professionelle"""
    ),
    (
        "Responsabilité de l'ingénieur face à lui même",
        """Passe après celle du client.

- Salaire
- Emploi
- Carrière
- Réputation
- Promotions"""
    ),
    (
        "Responsabilité de l'ingénieur face à la profession et ses confrères",
        """- Preserve son indépendnace
- Ne pas nuire à un confrère
- ne pas s'attribuer son travail
- collaborer avec l'ordre"""
    ),
    (
        "Article 2.01",
        """Obligation envers l'homme

L'ingénieur doit tenir compte des conséquences de son travail sur:
- L'environnement
- La vie
- La santé
- La propriété des personnes

Protège le publique en considérant les conséquence de ses travaux"""
    ),
    (
        "Article 2.02",
        """Améliorations des services

Constribuer à améliorer les services d'ingénierie"""
    ),
    (
        "Article 2.03",
        """Avertir des dangers.

Si ses travaux sont dangereux pour la sécurité publique, il a l'obligation d'avertir
- Responsable des travaux
- ou l'OIQ"""
    ),
    (
        "Article 2.04",
        """Connnaissances suffisantes

On doit donner un avis qui repose sur
- Des connaissances suffisantes
- Des convictions honnêtes

Parle professionnellement seulement si tu sais de quoi tu parles.

Pas de préférence personnelle ou opinion politique"""
    ),
    (
        "Article 2.05",
        "Éducation et information\n\nFavorise le partage et la diffusion des connaissances dans son domaine"
    ),
    (
        "Contractualisme",
        """Un règle est justifiable si elle peut être acceptée par les personnes concernés, même si elles ont des valeurs ou vision du monde différentes

Les personnes qui délibère doivent être
- Raisonnables
- Libres
- Bien informées

On peut s'entendre sur une sorte de contrat, qui crée des règles, des droits, des devoirs et des sanctions.

Pas besoin de tous avoir la même morale, on peut quand même s'entendre sur des règles permettant de vivre ensemble"""
    ),
    (
        "Le problème d'action collective",
        """Ce qui est rationnel et avantageux pour chaque individu séparément peut produire un résultat mauvais pour tout le monde collectivement.

Exemple:
- Surpêche
- Production GES

La pêche est rationnel individuellement, mais pas à grande échelle collectivement."""
    ),
    (
        "Pourquoi avons nous besoin de systèmes normatifs?",
        """Parce que les règles peuvent modifier les incitatifs et empêcher les individus de toujours choisir l'option opportuniste

Exemple:
Une intersection sans lumière, le choix dans l'intérêt de tout le monde est de passer immédiatement, ce qui ne fonctionne pas dans le collectif.

Les règles empêche de choisir toujours l'option opportuniste

Individuellement, on perd quelque secondes, collectivement tout le monde en bénéficie."""
    ),
    (
        "Liens entre système normatif et contractualisme",
        """Même si chaque individu préfère parfois être libre et faire ce qu'il veut, les individus peuvent rationnellement accepter de limiter leur propre liberté à condition que les autres fassent pareil"""
    ),
    (
        "Pourquoi les sytèmes normatif existent?",
        """Problème d'action collective
--> Chacun suit son intérêt
--> Résultat collectif mauvais

Dilemme prisonnier montre cela

Contractualisme
--> On reconnait notre intérêt commun
--> On accept ensemble certaine règle, même si elles peuvent limité notre liberté

Système normatif
--> Ces règles encadrent nos comportement
--> Droit + obligation + sanction"""
    ),
    (
        "Qu'est-ce qu'une valeur?",
        "Une valeur est un principe qui oriente nos actions et représente quelque chose qu'on considère important ou souhaitable."
    ),
    (
        "Dilemme du prisonnier",
        """Deux individus ont chacun intérêt, individuellement, à trahir l'autre. Si les deux font ce choix rationnel individuellement, ils obtiennent pourtant un résultat collectif pire que s'ils coopéraient.

→ Illustre un problème d'action collective.
→ Les systèmes normatifs peuvent modifier les incitatifs pour favoriser la coopération."""
    ),
    (
        "équilibre de Nash",
        "chacun trahit"
    ),
    (
        "optimum de Pareto",
        "les deux coopèrent"
    ),
]


# ============================================================
# Algorithme d'apprentissage
# ============================================================

from study_engine import Phase, Question, RoundStatus, StudyConfig, StudySession


# ============================================================
# Interface
# ============================================================

@dataclass
class CardView:
    question: Question
    showing_answer: bool = False
    answered: bool = False
    correct: bool | None = None
    typed_response: str = ""


class FlashcardLearnApp(tk.Tk):
    BG = "#F6F7FB"
    CARD_BG = "#FFFFFF"
    TEXT = "#2E3856"
    MUTED = "#6B7280"
    BORDER = "#D9DCE7"
    BLUE = "#4255FF"
    BLUE_HOVER = "#3144E8"
    RED = "#FF725B"
    RED_HOVER = "#E95F49"
    GREEN = "#23B26D"

    def __init__(self, config=None):
        super().__init__()
        self.title("Flashcard Learn")
        self.geometry("980x720")
        self.minsize(760, 600)
        self.configure(bg=self.BG)

        self.session = StudySession(FLASHCARDS, config=replace(config or StudyConfig(),
                                                            allow_multiple_choice=False,
                                                            allow_reverse_direction=False))
        self.scheduler = self.session
        self.current_card = None
        self.showing_definition = False
        self.awaiting_continue = False
        self.card_history = []
        self.history_index = -1
        self.history_context = None
        self.transition_message = ""
        self.session_correct = 0
        self.session_wrong = 0
        self.streak = 0
        self._save_error_shown = False
        self._load_progress()

        self._build_ui()
        self.bind("<space>", self._space_flip)
        self.bind("<Left>", lambda event: self.navigate_card(-1, event))
        self.bind("<Right>", lambda event: self.navigate_card(1, event))
        self.bind("<KeyPress-1>", lambda event: self._grade_shortcut(False, event))
        self.bind("<KeyPress-2>", lambda event: self._grade_shortcut(True, event))

        # Run shortcuts before widget defaults, including Text key handling and
        # the focused button's Space activation.
        widgets = list(self.winfo_children())
        while widgets:
            widget = widgets.pop()
            tags = widget.bindtags()
            widget.bindtags((str(self),) + tuple(tag for tag in tags if tag != str(self)))
            widgets.extend(widget.winfo_children())

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.load_next_card()

    def _load_progress(self):
        try:
            data = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
            if data.get("version") == StudySession.VERSION:
                data["config"]["allow_multiple_choice"] = False
                data["config"]["allow_reverse_direction"] = False
            self.session.restore(data)
            self.session_correct = self.session.session_correct
            self.session_wrong = self.session.session_wrong
            self.streak = self.session.streak
            return None
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError) as error:
            messagebox.showwarning(
                "Sauvegarde non chargée",
                f"Impossible de charger la progression : {error}\n"
                "Une nouvelle session va commencer.",
                parent=self,
            )
            return None

    def _save_progress(self):
        data = self.session.to_dict()
        temporary_path = None
        try:
            # Replace only after a complete write, keeping the previous save intact.
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                             dir=PROGRESS_PATH.parent, delete=False) as file:
                temporary_path = Path(file.name)
                json.dump(data, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, PROGRESS_PATH)
            self._save_error_shown = False
            return True
        except OSError as error:
            if not self._save_error_shown:
                messagebox.showwarning(
                    "Progression non sauvegardée",
                    f"Impossible de sauvegarder la progression : {error}", parent=self,
                )
                self._save_error_shown = True
            return False
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _on_close(self):
        if self._save_progress():
            self.destroy()

    def _build_ui(self):
        # Reserve rows for the controls; only the card grows or shrinks.
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)
        # ---------- En-tête ----------
        header = tk.Frame(self, bg=self.BG)
        header.grid(row=0, column=0, sticky="ew", padx=34, pady=(24, 8))

        self.heading_label = tk.Label(
            header,
            text="APPRENDRE",
            font=("Arial", 11, "bold"),
            fg=self.BLUE,
            bg=self.BG,
        )
        self.heading_label.pack(side="left")

        self.mode_btn = tk.Button(
            header, text="Réviser", command=self.toggle_mode, font=("Arial", 9, "bold"),
            bg=self.CARD_BG, fg=self.TEXT, bd=0, padx=12, pady=8,
        )
        self.mode_btn.pack(side="left", padx=12)

        tk.Button(
            header,
            text="Réinitialiser la progression",
            font=("Arial", 9, "bold"),
            fg=self.TEXT,
            bg=self.CARD_BG,
            activebackground=self.BORDER,
            activeforeground=self.TEXT,
            bd=0,
            padx=12,
            pady=8,
            cursor="hand2",
            command=self.restart,
        ).pack(side="right", padx=(16, 0))

        self.counter_label = tk.Label(
            header,
            text="",
            font=("Arial", 11, "bold"),
            fg=self.TEXT,
            bg=self.BG,
        )
        self.counter_label.pack(side="right")

        # ---------- Barre de progression ----------
        progress_wrap = tk.Frame(self, bg=self.BORDER, height=10)
        progress_wrap.grid(row=1, column=0, sticky="ew", padx=34, pady=(4, 18))

        self.progress_fill = tk.Frame(progress_wrap, bg=self.GREEN, height=10)
        self.progress_fill.place(relx=0, rely=0, relheight=1, relwidth=0)

        # ---------- Statistiques ----------
        stats = tk.Frame(self, bg=self.BG)
        stats.grid(row=2, column=0, sticky="ew", padx=34, pady=(0, 14))

        self.status_label = tk.Label(
            stats,
            text="",
            font=("Arial", 10),
            fg=self.MUTED,
            bg=self.BG,
        )
        self.status_label.pack(side="left")

        self.streak_label = tk.Label(
            stats,
            text="",
            font=("Arial", 10, "bold"),
            fg=self.TEXT,
            bg=self.BG,
        )
        self.streak_label.pack(side="right")

        self.round_notice = tk.Label(self, text="", font=("Arial", 10, "bold"),
                                     fg=self.BLUE, bg=self.BG, wraplength=850)
        self.round_notice.grid(row=3, column=0, sticky="ew", padx=34, pady=(0, 8))

        # ---------- Carte ----------
        card_outer = tk.Frame(self, bg=self.BG)
        card_outer.grid(row=4, column=0, sticky="nsew", padx=34, pady=(0, 16))

        self.card = tk.Frame(
            card_outer,
            bg=self.CARD_BG,
            highlightbackground=self.BORDER,
            highlightthickness=1,
            cursor="hand2",
        )
        self.card.pack(fill="both", expand=True)
        self.card.grid_columnconfigure(0, weight=1)
        self.card.grid_rowconfigure(1, weight=1)

        self.side_label = tk.Label(
            self.card,
            text="TERME",
            font=("Arial", 10, "bold"),
            fg=self.MUTED,
            bg=self.CARD_BG,
        )
        self.side_label.grid(row=0, column=0, sticky="w", padx=38, pady=(20, 12))

        text_container = tk.Frame(self.card, bg=self.CARD_BG)
        text_container.grid(row=1, column=0, sticky="nsew", padx=38, pady=(0, 12))

        self.card_text = tk.Text(
            text_container,
            wrap="word",
            height=1,
            width=1,
            bd=0,
            highlightthickness=0,
            bg=self.CARD_BG,
            fg=self.TEXT,
            font=("Arial", 19),
            cursor="hand2",
            padx=0,
            pady=0,
            relief="flat",
        )
        scrollbar = tk.Scrollbar(text_container, command=self.card_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.card_text.configure(yscrollcommand=scrollbar.set)
        self.card_text.pack(side="left", fill="both", expand=True)
        self.card_text.configure(state="disabled")

        self.question_controls = tk.Frame(self.card, bg=self.CARD_BG)
        self.question_controls.grid(row=2, column=0, sticky="ew", padx=38, pady=8)
        self.answer_entry = tk.Entry(self.question_controls, font=("Arial", 14))
        self.answer_entry.bind("<Return>", self.submit_answer)
        self.submit_btn = tk.Button(self.question_controls, text="Vérifier", command=self.submit_answer)
        self.continue_btn = tk.Button(self.question_controls, text="Suivante →",
                                      command=self.continue_after_answer)

        self.flip_hint = tk.Label(
            self.card,
            text="Clique sur la carte ou appuie sur Espace pour voir la définition",
            font=("Arial", 10),
            fg=self.MUTED,
            bg=self.CARD_BG,
            wraplength=650,
        )
        self.flip_hint.grid(row=3, column=0, sticky="ew", padx=20, pady=(8, 16))

        for widget in (self.card, self.side_label, self.card_text, self.flip_hint, text_container):
            widget.bind("<Button-1>", self.flip_card)

        # ---------- Boutons ----------
        buttons = tk.Frame(self, bg=self.BG)
        buttons.grid(row=5, column=0, sticky="ew", padx=34, pady=(0, 12))

        self.wrong_btn = tk.Button(
            buttons,
            text="✕  Incorrect (1)",
            font=("Arial", 12, "bold"),
            bg=self.CARD_BG,
            fg=self.RED,
            activebackground="#FFF2EF",
            activeforeground=self.RED_HOVER,
            bd=0,
            relief="flat",
            padx=24,
            pady=15,
            cursor="hand2",
            command=lambda: self.grade(False),
            state="disabled",
        )
        self.wrong_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.correct_btn = tk.Button(
            buttons,
            text="✓  Bon (2)",
            font=("Arial", 12, "bold"),
            bg=self.BLUE,
            fg="white",
            activebackground=self.BLUE_HOVER,
            activeforeground="white",
            bd=0,
            relief="flat",
            padx=24,
            pady=15,
            cursor="hand2",
            command=lambda: self.grade(True),
            state="disabled",
        )
        self.correct_btn.pack(side="left", fill="x", expand=True, padx=(8, 0))

        navigation = tk.Frame(self, bg=self.BG)
        navigation.grid(row=6, column=0, sticky="ew", padx=34, pady=(0, 12))
        self.previous_btn = tk.Button(
            navigation, text="← Précédente", command=lambda: self.navigate_card(-1),
            font=("Arial", 11), bg=self.CARD_BG, fg=self.TEXT, bd=0, padx=18, pady=8,
        )
        self.previous_btn.pack(side="left")
        self.next_btn = tk.Button(
            navigation, text="Suivante →", command=lambda: self.navigate_card(1),
            font=("Arial", 11), bg=self.CARD_BG, fg=self.TEXT, bd=0, padx=18, pady=8,
        )
        self.next_btn.pack(side="right")

        # ---------- Bas ----------
        footer = tk.Frame(self, bg=self.BG)
        footer.grid(row=7, column=0, sticky="ew", padx=34, pady=(0, 20))

        tk.Label(
            footer,
            text="Espace = retourner  •  ← / → = précédente / suivante  •  1 = Incorrect  •  2 = Bon",
            font=("Arial", 9),
            fg=self.MUTED,
            bg=self.BG,
        ).pack(side="left")

    def _set_card_text(self, text, size):
        self.card_text.configure(state="normal", font=("Arial", size))
        self.card_text.delete("1.0", "end")
        self.card_text.insert("1.0", text)
        self.card_text.configure(state="disabled")
        self.card_text.yview_moveto(0)

    def load_next_card(self):
        context = self._navigation_context()
        if context != self.history_context:
            self.card_history = []
            self.history_index = -1
            self.history_context = context
        question = self.session.next_question()
        # Older saves may still contain quizzes; resume them as flashcards.
        if question is not None and question.kind == "multiple_choice":
            question = replace(question, kind="free_recall", options=())
            self.session.current_question = question
        # Keep saved reverse prompts on the same card, starting with its term.
        if question is not None and question.direction == "reverse":
            question = replace(question, direction="forward", prompt=question.answer, answer=question.prompt)
            self.session.current_question = question
        if question is not None:
            if not self.card_history or self.card_history[-1].question != question or self.card_history[-1].answered:
                self.card_history.append(CardView(question))
            self.history_index = len(self.card_history) - 1
            self._render_card()
        else:
            self.question = None
            self.awaiting_continue = False
            self._hide_question_controls()
            self.show_completion()
        self._save_progress()

    def _navigation_context(self):
        return (self.session, self.session.mode, self.session.phase, self.session.current_round_index)

    def _viewing_history(self):
        return self.history_index < len(self.card_history) - 1

    def _render_card(self):
        view = self.card_history[self.history_index]
        self.question = view.question
        self.awaiting_continue = view.answered
        self.showing_definition = view.showing_answer
        historical = self._viewing_history()
        self._hide_question_controls()
        self.current_card = next((c for c in self.session.cards
                                  if self.question and c.id == self.question.card_id), None)
        label = "DÉFINITION → TERME" if self.question.direction == "reverse" else "TERME → DÉFINITION"
        self.side_label.configure(text=label)
        self.round_notice.configure(text=self.transition_message)
        self.wrong_btn.configure(state="disabled")
        self.correct_btn.configure(state="disabled")
        if self.showing_definition:
            label = "TERME" if self.question.direction == "reverse" else "DÉFINITION"
            if view.correct is not None:
                label = "BONNE RÉPONSE" if view.correct else "CORRECTION"
            self.side_label.configure(text=label)
            self._set_card_text(self.question.answer, 16)
            if not self.awaiting_continue and not historical:
                self.wrong_btn.configure(state="normal")
                self.correct_btn.configure(state="normal")
                self.flip_hint.configure(text="Évalue ta réponse : 1 = Incorrect, 2 = Bon. Espace pour retourner.")
        elif self.awaiting_continue or historical:
            self._set_card_text(self.question.prompt, 18)
        elif self.question.kind == "typed":
            self._set_card_text(self.question.prompt, 18)
            self.answer_entry.delete(0, "end")
            self.answer_entry.insert(0, view.typed_response)
            self.answer_entry.pack(side="left", fill="x", expand=True)
            self.submit_btn.pack(side="right", padx=8)
            self.answer_entry.focus_set()
            self.flip_hint.configure(text="Écris ta réponse, puis appuie sur Entrée.")
        else:
            self._set_card_text(self.question.prompt, 18)
            self.flip_hint.configure(text="Rappelle la réponse avant de cliquer ou d'appuyer sur Espace.")
        if historical:
            self.flip_hint.configure(text="Carte précédente · Espace pour retourner · → pour revenir aux cartes suivantes.")
        elif self.awaiting_continue:
            self.flip_hint.configure(text="Espace pour retourner la carte · → ou Suivante pour continuer.")
            self.continue_btn.pack()
            self.continue_btn.focus_set()
        self._update_navigation()
        self.update_stats()

    def flip_card(self, event=None):
        if self.current_card is None:
            return
        view = self.card_history[self.history_index]
        # Revealing an unanswered typed question switches to self-assessment.
        if not view.answered and not self._viewing_history() and view.question.kind != "free_recall":
            view.question = replace(view.question, kind="free_recall", options=())
            self.session.current_question = view.question
            self._save_progress()
        view.showing_answer = not view.showing_answer
        self._render_card()

    def _update_navigation(self):
        can_go_back = (self.current_card is not None and self.history_index > 0
                       and self.history_context == self._navigation_context())
        self.previous_btn.configure(state="normal" if can_go_back else "disabled")
        self.next_btn.configure(state="normal" if self.current_card is not None else "disabled")

    def navigate_card(self, direction, event=None):
        if self._editing_answer(event):
            return None
        if self.current_card is None:
            return "break"
        if self.question.kind == "typed" and not self.awaiting_continue and not self._viewing_history():
            self.card_history[self.history_index].typed_response = self.answer_entry.get()
        if direction < 0:
            if self.history_index > 0 and self.history_context == self._navigation_context():
                self.history_index -= 1
                self._render_card()
        elif self.history_index + 1 < len(self.card_history):
            self.history_index += 1
            self._render_card()
        else:
            # Skipping a prompt never records a success or a mistake.
            # The saved pending question always belongs to the newest view.
            self.session.current_question = None
            self.load_next_card()
        return "break"

    def grade(self, knew_it):
        if (self.current_card is None or not self.showing_definition or self.awaiting_continue
                or self._viewing_history() or self.question.kind != "free_recall"):
            return
        self._record_answer(knew_it)
        self.navigate_card(1)

    def _record_answer(self, correct):
        old_phase, old_round = self.session.phase, self.session.current_round_index
        old_size = len(self.session.active_pool)
        self.session.grade(correct)
        view = self.card_history[self.history_index]
        view.answered = True
        view.correct = correct
        view.showing_answer = True
        self.session_correct = self.session.session_correct
        self.session_wrong = self.session.session_wrong
        self.streak = self.session.streak
        self.transition_message = ""
        if self.session.mode == "LEARN" and old_phase != self.session.phase:
            if self.session.phase == Phase.FINAL_MASTERY_ROUND:
                self.transition_message = "Tous les groupes sont maîtrisés. Maîtrise finale : toutes les cartes mélangées."
            elif self.session.complete:
                self.transition_message = "Maîtrise finale réussie : toutes les cartes sont maîtrisées."
        elif self.session.mode == "LEARN" and old_round != self.session.current_round_index:
            self.transition_message = f"Groupe {old_round + 1} terminé : {old_size} cartes maîtrisées. Groupe suivant."

    def _hide_question_controls(self):
        for widget in (self.answer_entry, self.submit_btn, self.continue_btn):
            widget.pack_forget()

    def submit_answer(self, event=None):
        if self.current_card is None or self.awaiting_continue or self._viewing_history() or self.question.kind != "typed":
            return "break"
        response = " ".join(self.answer_entry.get().casefold().split())
        if response:
            expected = " ".join(self.question.answer.casefold().split())
            self._show_answer_feedback(response == expected)
        return "break"

    def _show_answer_feedback(self, correct):
        self._record_answer(correct)
        self._render_card()
        self._save_progress()

    def continue_after_answer(self):
        if self.awaiting_continue:
            self.navigate_card(1)

    def toggle_mode(self):
        mode = "REVIEW" if self.session.mode == "LEARN" else "LEARN"
        self.session.set_mode(mode)
        self.transition_message = "Révisions espacées des groupes terminés." if mode == "REVIEW" else "Retour à l'apprentissage."
        self.load_next_card()

    def update_stats(self):
        mastered = self.session.mastered_count
        total = self.session.total
        final_mastered = sum(c.final.mastered for c in self.session.cards)
        initial_mastered = sum(c.mastered for c in self.session.cards)
        pct = (initial_mastered + final_mastered) / (2 * total) if total else 1

        self.progress_fill.place(relwidth=pct)
        if self.session.mode == "REVIEW":
            due = self.session.due_review_count
            counter = f"Révision espacée · {due} à revoir"
        elif self.session.phase == Phase.INITIAL_ROUND_LEARNING:
            position = f"Groupe {self.session.current_round_index + 1}/{len(self.session.rounds)}"
            counter = f"{position} · {self.session.round_mastered_count}/{len(self.session.active_pool)}"
        elif self.session.phase == Phase.FINAL_MASTERY_ROUND:
            counter = f"Maîtrise finale · {mastered}/{total}"
        else:
            counter = f"Ensemble maîtrisé · {mastered}/{total}"
        self.counter_label.configure(text=counter)
        evidence = self.session.progress_for(self.current_card) if self.current_card else None
        familiarity = {"NEW": "Nouvelle", "UNTESTED": "À confirmer", "LEARNING": "En apprentissage",
                       "FAMILIAR": "Familière", "MASTERED": "Maîtrisée"}.get(evidence.state, "") if evidence else ""
        self.heading_label.configure(text="RÉVISER" if self.session.mode == "REVIEW" else "APPRENDRE")
        self.mode_btn.configure(text="Apprendre" if self.session.mode == "REVIEW" else "Réviser",
                                state="normal" if self.session.mode == "REVIEW" or any(r.status == RoundStatus.COMPLETED for r in self.session.rounds) else "disabled")

        self.status_label.configure(
            text=(
                f"{familiarity}   •   "
                f"{self.session_correct} bonnes   •   "
                f"{self.session_wrong} à revoir"
            )
        )
        self.streak_label.configure(text=f"Série : {self.streak}")

    def show_completion(self):
        self.current_card = None
        self.showing_definition = False

        self.round_notice.configure(text=self.transition_message)
        if self.session.mode == "REVIEW":
            self.side_label.configure(text="RÉVISIONS À JOUR")
            text = "Aucune révision à faire maintenant.\nReviens à Apprendre pour continuer ta progression."
            self.flip_hint.configure(text="Les révisions seront disponibles à leur prochaine échéance.")
            self.after(30000, self._check_reviews)
        else:
            self.side_label.configure(text="ENSEMBLE MAÎTRISÉ")
            text = "Tous les groupes et la maîtrise finale sont terminés.\nToutes les cartes ont été maîtrisées à nouveau dans l'ensemble mélangé."
            self.flip_hint.configure(text="Utilise Réviser pour les révisions espacées.")
        self._set_card_text(f"{text}\n\nBonnes évaluations : {self.session_correct}\nÀ revoir : {self.session_wrong}", 22)
        self.wrong_btn.configure(state="disabled")
        self.correct_btn.configure(state="disabled")
        self._update_navigation()
        self.update_stats()

    def _check_reviews(self):
        if self.session.mode == "REVIEW" and self.current_card is None:
            self.load_next_card()

    def restart(self):
        if not messagebox.askyesno(
            "Réinitialiser la progression",
            "Effacer toute la progression sauvegardée et recommencer à zéro ?",
            parent=self,
        ):
            return
        raw = [(c.term, c.definition) for c in self.scheduler.cards]
        self.session = StudySession(raw, config=self.session.config)
        self.scheduler = self.session
        self.session_correct = 0
        self.session_wrong = 0
        self.streak = 0
        self.transition_message = "Progression réinitialisée."
        self.load_next_card()

    def _space_flip(self, event):
        if self._editing_answer(event):
            return None
        self.flip_card()
        return "break"

    def _grade_shortcut(self, knew_it, event):
        if self._editing_answer(event):
            return None
        self.grade(knew_it)
        return "break"

    def _editing_answer(self, event):
        return (event is not None and event.widget == self.answer_entry and self.question is not None
                and self.question.kind == "typed" and not self.awaiting_continue and not self._viewing_history())

if __name__ == "__main__":
    app = FlashcardLearnApp()
    app.mainloop()
