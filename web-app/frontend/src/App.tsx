import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  ArrowDown, ArrowLeft, ArrowRight, BookOpen, Check, CheckCircle2, ChevronRight,
  CircleHelp, Cloud, Flame, Flower2, Focus, Keyboard, Layers3, Leaf,
  LockKeyhole, RotateCcw, Settings2, Sparkles, Sprout, Trophy, X,
} from 'lucide-react'
import type { Action, CardState, SetSelection, StudyState } from './types'
import { apiFetch, memoBase } from './api'
import { useAccount } from './AuthGate'

const stateLabels: Record<CardState, string> = {
  NEW: 'Nouvelle', UNTESTED: 'À confirmer', LEARNING: 'En apprentissage',
  FAMILIAR: 'Familière', MASTERED: 'Maîtrisée',
}

function Key({ children }: { children: ReactNode }) {
  return <kbd>{children}</kbd>
}

function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const node = dialog.current!
    node.showModal()
    const cancel = (event: Event) => { event.preventDefault(); onClose() }
    node.addEventListener('cancel', cancel)
    return () => { node.removeEventListener('cancel', cancel); node.close() }
  }, [onClose])
  return <dialog ref={dialog} className="modal" aria-label={title} onClick={event => {
    if (event.target === dialog.current) {
      const rect = dialog.current.getBoundingClientRect()
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose()
    }
  }}>
    <div className="modal-heading"><h2>{title}</h2><button className="icon-button" aria-label="Fermer" onClick={onClose}><X size={20} /></button></div>
    {children}
  </dialog>
}

export default function App({ deck, onLibrary }: { deck?: SetSelection; onLibrary?: () => void }) {
  const account = useAccount()
  const [study, setStudy] = useState<StudyState | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState('')
  const [modal, setModal] = useState<'help' | 'settings' | 'reset' | 'group' | null>(null)
  const [focusMode, setFocusMode] = useState(false)
  const [announcement, setAnnouncement] = useState('')
  const stateRef = useRef(study)
  const requestPending = useRef(false)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const cardTextRef = useRef<HTMLDivElement>(null)
  const closeModal = useCallback(() => setModal(null), [])
  const studyQuery = deck ? `?set_id=${encodeURIComponent(deck.id)}&version=${deck.version}` : ''
  const deckTitle = deck?.title || 'Éthique de l’ingénieur'
  stateRef.current = study

  const receive = useCallback((data: StudyState) => {
    setStudy(data)
    stateRef.current = data
    setDraft(data.question?.typed_response ?? '')
  }, [])

  const load = useCallback(async () => {
    try {
      const response = await apiFetch('state' + studyQuery, { cache: 'no-store' })
      if (!response.ok) throw new Error()
      receive(await response.json())
      setError('')
    } catch {
      setError('Impossible de joindre le serveur. Vérifie que le backend est lancé, puis réessaie.')
    }
  }, [receive, studyQuery])

  useEffect(() => { void load() }, [load])

  const act = useCallback(async (action: Action) => {
    if (requestPending.current || !stateRef.current) return
    requestPending.current = true
    setBusy(true)
    setError('')
    try {
      const response = await apiFetch('actions' + studyQuery, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...action, revision: stateRef.current.revision }),
      })
      if (!response.ok) {
        const result = await response.json()
        if (response.status === 409) await load()
        throw new Error(typeof result.detail === 'string' ? result.detail : 'Cette action n’a pas pu être enregistrée.')
      }
      receive(await response.json())
      if (action.type === 'grade') setAnnouncement(action.correct ? 'Bonne réponse enregistrée. Carte suivante.' : 'Carte à revoir enregistrée. Carte suivante.')
      if (action.type === 'settings') setAnnouncement('Préférence enregistrée.')
      if (action.type === 'reset') setModal(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'La connexion a été interrompue. Actualise la session avant de continuer.')
      // Recover the authoritative state if the server saved before the connection broke.
      if (caught instanceof TypeError) {
        const result = await apiFetch('state' + studyQuery, { cache: 'no-store' }).catch(() => null)
        if (result?.ok) receive(await result.json())
      }
    } finally {
      requestPending.current = false
      setBusy(false)
    }
  }, [load, receive, studyQuery])

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (modal || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
      const target = event.target as HTMLElement
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable) return
      const question = stateRef.current?.question
      if (!question || busy || event.repeat) return
      if (event.code === 'Space') { event.preventDefault(); void act({ type: 'flip' }) }
      if (event.key === 'ArrowLeft' && question.can_previous) { event.preventDefault(); void act({ type: 'navigate', direction: -1, response: draft }) }
      if (event.key === 'ArrowRight') { event.preventDefault(); void act({ type: 'navigate', direction: 1, response: draft }) }
      if ((event.key === '1' || event.key === '2') && question.can_grade) {
        event.preventDefault(); void act({ type: 'grade', correct: event.key === '2' })
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [act, busy, draft, modal])

  useEffect(() => {
    if (study?.mode !== 'REVIEW' || study.question) return
    const timer = window.setInterval(() => { void act({ type: 'refresh' }) }, 30_000)
    return () => window.clearInterval(timer)
  }, [study?.mode, study?.question, act])

  useEffect(() => {
    cardTextRef.current?.scrollTo(0, 0)
    if (study?.question?.kind === 'typed' && !study.question.showing_answer && !study.question.historical && !study.question.answered) inputRef.current?.focus()
  }, [study?.question?.card_id, study?.question?.position, study?.question?.showing_answer, study?.question?.kind])

  if (!study) return <div className="boot-screen">
    <div className="brand-mark"><Flower2 size={30} /></div><h1>mémo<span>.</span></h1>
    {error ? <><p role="alert">{error}</p><button className="primary-button" onClick={() => void load()}><RotateCcw size={17} /> Réessayer</button></> : <p className="loading-text">Ton espace d’étude se prépare…</p>}
    {onLibrary && <button className="secondary-button" onClick={onLibrary}>Mes ensembles</button>}
  </div>

  const q = study.question
  const isReview = study.mode === 'REVIEW'
  const isFinal = study.phase === 'FINAL_MASTERY_ROUND'
  const percentage = Math.round(study.progress * 100)
  const groupTitle = isReview ? 'Révisions espacées' : isFinal ? 'Maîtrise finale' : study.complete ? 'Ensemble maîtrisé' : `Groupe ${study.active_round_index + 1}`
  const groupCaption = isReview ? `${study.due_reviews} carte${study.due_reviews === 1 ? '' : 's'} à revoir` : isFinal ? 'Toutes les cartes, mélangées' : study.complete ? 'Une belle étape de franchie' : `${study.active_total} cartes · Rappel actif`
  const side = q?.showing_answer ? q.direction === 'reverse' ? 'TERME' : 'DÉFINITION' : q?.direction === 'reverse' ? 'DÉFINITION' : 'TERME'
  const typed = q?.kind === 'typed' && !q.showing_answer && !q.answered && !q.historical
  const answered = study.correct + study.wrong

  return <div className={`app-shell ${focusMode ? 'is-focused' : ''}`}>
    <aside className="sidebar">
      <a className="brand" href={memoBase} aria-label="Mémo, accueil"><Flower2 size={29} strokeWidth={1.7} /><span>mémo<span className="brand-dot">.</span></span></a>
      <div className="sidebar-caption">UN PEU CHAQUE JOUR.</div>
      <nav className="main-nav" aria-label="Modes d’étude">
        <span className="nav-label">TON ESPACE</span>
        <button className={`nav-item ${!isReview ? 'active' : ''}`} aria-current={!isReview ? 'page' : undefined} disabled={busy} onClick={() => void act({ type: 'mode', mode: 'LEARN' })}><BookOpen size={19} /><span>Apprendre</span><ChevronRight size={16} /></button>
        <button className={`nav-item ${isReview ? 'active' : ''}`} aria-current={isReview ? 'page' : undefined} disabled={busy || !study.review_available} title={!study.review_available ? 'Termine un groupe pour débloquer les révisions' : 'Réviser les cartes arrivées à échéance'} onClick={() => void act({ type: 'mode', mode: 'REVIEW' })}><RotateCcw size={18} /><span>Révisions</span>{study.review_available ? <span className="nav-count">{study.due_reviews}</span> : <LockKeyhole size={14} />}</button>
      </nav>
      <div className="sidebar-deck">
        <span className="nav-label">TON ENSEMBLE</span>
        <div className="deck-cover"><div className="cover-lines" /><Sprout size={57} strokeWidth={1.2} /><span>LE SAVOIR<br />SE CULTIVE.</span><span className="cover-index">{deck ? `VERSION ${deck.version}` : '01 / ÉTHIQUE'}</span></div>
        <h3>{deckTitle}</h3><p>{study.total} cartes pour y voir plus clair.</p>
      </div>
      <div className="sidebar-bottom"><div className="user-avatar">{account?.user.display_name.charAt(0) || 'M'}</div><div><strong>{account?.user.display_name || 'Mon espace personnel'}</strong><span>À mon rythme</span></div><Leaf size={17} /></div>
    </aside>

    <div className="workspace">
      <header className="topbar">
        <div className="breadcrumb"><span>Mon espace</span><ChevronRight size={13} /><strong>{isReview ? 'Révisions' : 'Apprendre'}</strong></div>
        <div className={`topbar-actions ${onLibrary ? 'has-library' : ''}`}><span className={`save-status ${busy ? 'saving' : ''}`}><Cloud size={15} />{busy ? 'Enregistrement…' : 'Progression sauvegardée'}</span>{onLibrary && <button className="secondary-button library-open" onClick={onLibrary} disabled={busy} aria-label="Mes ensembles"><Layers3 size={16} /><span>Mes ensembles</span></button>}<button className="icon-button" title="Paramètres" aria-label="Paramètres" onClick={() => setModal('settings')}><Settings2 size={19} /></button></div>
      </header>

      <main>
        <div className="page-heading"><div><div className="eyebrow"><span />{isReview ? 'ENTRETENIR SES ACQUIS' : 'UNE CARTE À LA FOIS'}</div><h1>{isReview ? 'Ce que tu sais, reste.' : 'Le savoir se cultive.'}</h1><p>{isReview ? 'Un petit rappel aujourd’hui, une mémoire plus solide demain.' : 'Prends le temps de comprendre. Le reste viendra.'}</p></div><div className="streak-pill"><Flame size={18} /><strong>{study.streak}</strong><span>de suite</span></div></div>

        {error && <div className="error-banner" role="alert"><span>{error}</span><button onClick={() => void load()}>Actualiser</button></div>}
        {study.notice && <div className="notice-banner" role="status"><Sparkles size={17} />{study.notice}</div>}
        <span className="sr-only" role="status" aria-live="polite">{announcement}</span>

        <div className="study-layout">
          <section className="study-column" aria-label="Session d’étude">
            <div className="session-heading"><div className="session-icon"><Layers3 size={20} /></div><div><h2>{groupTitle}<span className="session-divider">/</span><span className="deck-title-inline">{deckTitle}</span></h2><p>{groupCaption}</p></div><button className={`icon-button focus-button ${focusMode ? 'selected' : ''}`} title={focusMode ? 'Quitter le mode concentration' : 'Mode concentration'} aria-label={focusMode ? 'Quitter le mode concentration' : 'Mode concentration'} aria-pressed={focusMode} onClick={() => setFocusMode(!focusMode)}><Focus size={19} /></button></div>

            <div className="session-progress"><div className="thin-track"><div style={{ width: `${isReview ? 0 : study.active_total ? study.active_mastered / study.active_total * 100 : 100}%` }} /></div><span>{isReview ? 'Rappel espacé' : `${study.active_mastered} / ${study.active_total || study.total} maîtrisées`}</span></div>

            {q ? <>
              <div className="card-stack">
                <div className="paper-behind" />
                <div className={`flashcard ${q.showing_answer ? 'is-revealed' : ''}`}>
                  <div className="card-topline"><span className="card-side"><span className="tiny-dot" />{q.answered ? q.correct ? 'BIEN RETENU' : 'CORRECTION' : side}</span><span className={`familiarity state-${q.state.toLowerCase()}`}>{q.historical ? 'Carte précédente' : stateLabels[q.state]}</span></div>
                  <div className={`card-content ${q.showing_answer ? 'answer-content' : ''}`} ref={cardTextRef}>
                    <button className={`card-flip-area ${q.text.length > 220 ? 'long-text' : ''}`} aria-label="Retourner la carte" disabled={busy} onClick={() => void act({ type: 'flip' })}>{q.text}</button>
                  </div>
                  <div className="card-bottomline"><span>{q.direction === 'reverse' ? 'Définition → terme' : 'Terme → définition'}</span><button className="flip-mini" disabled={busy} onClick={() => void act({ type: 'flip' })}><RotateCcw size={14} /> Retourner<Key>espace</Key></button></div>
                </div>
              </div>

              <div className="card-navigation"><button className="navigation-button" aria-label="Carte précédente" disabled={!q.can_previous || busy} onClick={() => void act({ type: 'navigate', direction: -1, response: draft })}><ArrowLeft size={17} /><span>Précédente</span></button><span className="navigation-position">Carte <strong>{String(q.position).padStart(2, '0')}</strong>{q.historical && <span> / {String(q.history_length).padStart(2, '0')}</span>}</span><button className="navigation-button" aria-label="Carte suivante" disabled={busy} onClick={() => void act({ type: 'navigate', direction: 1, response: draft })}><span>Suivante</span><ArrowRight size={17} /></button></div>

              <div className="answer-actions">
                {q.historical ? <div className="history-message"><BookOpen size={17} /><span>Tu consultes une carte précédente. Reviens à la carte actuelle pour répondre.</span></div> : q.answered ? <><div className={`feedback ${q.correct ? 'correct-feedback' : 'wrong-feedback'}`}>{q.correct ? <CheckCircle2 size={18} /> : <RotateCcw size={18} />}{q.correct ? 'Bien joué, c’est la bonne réponse.' : 'Relis la correction. Tu la reverras au bon moment.'}</div><button className="primary-button" disabled={busy} onClick={() => void act({ type: 'navigate', direction: 1, response: draft })}>Continuer<ArrowRight size={17} /><Key>→</Key></button></> : typed ? <form className="typed-form" onSubmit={event => { event.preventDefault(); void act({ type: 'typed', response: draft }) }}><label htmlFor="typed-response">Rappelle-toi la réponse, puis écris-la.</label><textarea id="typed-response" ref={inputRef} value={draft} onChange={event => setDraft(event.target.value)} placeholder="Ta réponse…" rows={3} disabled={busy} onKeyDown={event => {
                  if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); if (draft.trim()) void act({ type: 'typed', response: draft }) }
                }} /><button className="primary-button" disabled={busy || !draft.trim()} type="submit">Vérifier ma réponse<Check size={17} /><Key>↵</Key></button><p>La réponse doit correspondre au texte de la carte. Majuscules et espaces sont ignorés.</p></form> : <>
                  {!q.showing_answer && <button className="primary-button reveal-button" disabled={busy} onClick={() => void act({ type: 'flip' })}>Révéler la réponse<ArrowDown size={17} /><Key>espace</Key></button>}
                  <div className={`grade-actions ${!q.can_grade ? 'not-ready' : ''}`}><button className="grade-button grade-wrong" disabled={!q.can_grade || busy} onClick={() => void act({ type: 'grade', correct: false })}><RotateCcw size={18} /><span>À revoir</span><Key>1</Key></button><button className="grade-button grade-correct" disabled={!q.can_grade || busy} onClick={() => void act({ type: 'grade', correct: true })}><Check size={19} /><span>Bien retenu</span><Key>2</Key></button></div>
                  <p className="recall-hint">{q.showing_answer ? 'Sois honnête avec toi-même. Chaque réponse aide à mieux apprendre.' : 'Essaie de répondre de tête avant de retourner la carte.'}</p>
                </>}
              </div>
            </> : <div className="empty-state"><div className="empty-illustration">{isReview ? <Leaf size={50} strokeWidth={1.3} /> : <Trophy size={50} strokeWidth={1.3} />}</div><span className="eyebrow">{isReview ? 'L’ESPRIT TRANQUILLE' : 'UN BEAU CHEMIN PARCOURU'}</span><h2>{isReview ? 'Tes révisions sont à jour.' : 'Tout est maîtrisé.'}</h2><p>{isReview ? 'Tes cartes reviendront quand ce sera le bon moment. Tu peux poursuivre ton apprentissage.' : 'Chaque carte a été maîtrisée dans son groupe, puis dans l’ensemble mélangé. Continue à entretenir tes acquis.'}</p>{isReview && study.next_review_at && <span className="next-review">Prochaine échéance : {new Intl.DateTimeFormat('fr-CA', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(study.next_review_at * 1000))}</span>}<button className="primary-button" disabled={busy || (!isReview && !study.review_available)} onClick={() => void act({ type: 'mode', mode: isReview ? 'LEARN' : 'REVIEW' })}>{isReview ? 'Revenir à l’apprentissage' : 'Passer aux révisions'}<ArrowRight size={17} /></button></div>}

            <div className="keyboard-shortcuts"><Keyboard size={15} /><span>À portée de clavier</span><span><Key>espace</Key> retourner</span><span><Key>←</Key><Key>→</Key> naviguer</span><span><Key>1</Key><Key>2</Key> évaluer</span></div>
          </section>

          <aside className="insights-column" aria-label="Progression">
            <section className="journey-panel"><div className="panel-title"><h2>Ton parcours</h2><span>{study.rounds.length} groupes</span></div><div className="journey-list">
              {study.rounds.map((round, index) => <div className={`journey-step ${round.status.toLowerCase()}`} key={round.id}><div className="journey-marker">{round.status === 'COMPLETED' ? <Check size={14} /> : round.status === 'LOCKED' ? <LockKeyhole size={12} /> : String(index + 1).padStart(2, '0')}</div><div><strong>Groupe {index + 1}</strong><span>{round.status === 'COMPLETED' ? 'Maîtrisé' : round.status === 'ACTIVE' ? `${round.mastered} sur ${round.total} maîtrisées` : `${round.total} cartes`}</span></div>{round.status === 'ACTIVE' && <span className="in-progress-dot" />}</div>)}
              <div className={`journey-step final-step ${study.final_status.toLowerCase()}`}><div className="journey-marker">{study.final_status === 'COMPLETED' ? <Check size={14} /> : <Sparkles size={15} />}</div><div><strong>Maîtrise finale</strong><span>{study.final_status === 'ACTIVE' ? `${study.final_mastered} sur ${study.total} maîtrisées` : study.final_status === 'COMPLETED' ? 'Tout est maîtrisé' : 'L’ensemble mélangé'}</span></div></div>
            </div><div className="journey-note"><LockKeyhole size={13} /><p>Un groupe maîtrisé débloque le suivant. Chaque chose en son temps.</p></div></section>

            <section className="global-progress-panel"><div className="progress-ring" role="progressbar" aria-label="Maîtrise globale" aria-valuenow={percentage} aria-valuemin={0} aria-valuemax={100} style={{ background: `conic-gradient(var(--green) ${percentage}%, #e8e9df 0)` }}><div><strong>{percentage}<span>%</span></strong></div></div><div><h3>Maîtrise globale</h3><p>Groupes + maîtrise finale</p><span>{study.initial_mastered + study.final_mastered} / {study.total * 2} validations</span></div></section>

            <section className="method-note"><div className="method-icon"><Sprout size={22} strokeWidth={1.6} /></div><span className="eyebrow">APPRENDRE POUR DE BON</span><h3>Le bon rappel,<br />au bon moment.</h3><p>Les cartes qui te résistent reviennent plus souvent. Celles que tu connais prennent un peu de recul.</p><button onClick={() => setModal('help')}>Comment ça marche<ArrowRight size={14} /></button></section>
          </aside>
        </div>

        <section className="session-summary" aria-label="Statistiques de la session"><div><span className="summary-icon green"><Check size={18} /></span><div><strong>{study.correct}</strong><span>bien retenues</span></div></div><div><span className="summary-icon terra"><RotateCcw size={17} /></span><div><strong>{study.wrong}</strong><span>à retravailler</span></div></div><div><span className="summary-icon neutral"><Layers3 size={18} /></span><div><strong>{answered}</strong><span>réponses données</span></div></div><button className="group-link" disabled={isReview || study.complete} onClick={() => setModal('group')}>Les cartes du groupe<ArrowRight size={16} /></button></section>
        <footer className="page-footer"><span>Fais de la place à ce qui compte.</span><button onClick={() => setModal('help')}><CircleHelp size={15} /> Un petit coup de main</button></footer>
      </main>
    </div>

    {modal === 'help' && <Modal title="Apprendre, simplement." onClose={closeModal}><div className="help-intro"><Sprout size={36} /><p>Un moteur qui suit tes progrès.<br />Un rythme qui te ressemble.</p></div><ol className="help-steps"><li><strong>Rappelle-toi avant de regarder.</strong><p>Lis le terme, formule ta réponse mentalement ou à voix haute, puis retourne la carte.</p></li><li><strong>Évalue ce que tu as retenu.</strong><p>« À revoir » enregistre une erreur. « Bien retenu » enregistre un succès. Un clic sur Suivante passe la carte sans l’évaluer.</p></li><li><strong>Progresse par petits groupes.</strong><p>Les {study.round_size} cartes de chaque groupe doivent être maîtrisées avant de passer au suivant. La maîtrise demande des succès répétés et espacés.</p></li><li><strong>Confirme tes acquis.</strong><p>La maîtrise finale mélange toutes les cartes et représente la seconde moitié de ta progression. Les révisions espacées entretiennent ensuite ta mémoire, séparément.</p></li></ol><div className="help-keyboard"><span><Key>espace</Key> Retourner</span><span><Key>←</Key><Key>→</Key> Naviguer</span><span><Key>1</Key> À revoir</span><span><Key>2</Key> Bien retenu</span></div><p className="modal-footnote">En saisie écrite, les touches servent à écrire. Entrée vérifie la réponse ; Maj + Entrée ajoute une ligne.</p></Modal>}
    {modal === 'settings' && <Modal title="À ta façon." onClose={closeModal}><p className="modal-description">Choisis comment pratiquer le rappel actif.</p><div className="setting-row"><div><strong>Réponse écrite</strong><p>Écris ta réponse et vérifie-la avec Entrée. Tu peux toujours retourner la carte pour t’autoévaluer.</p></div><button className={`toggle ${study.typed_recall ? 'on' : ''}`} role="switch" aria-label="Réponse écrite" aria-checked={study.typed_recall} disabled={busy} onClick={() => void act({ type: 'settings', typed: !study.typed_recall })}><span /></button></div><p className="setting-tip">La vérification ignore la casse et les espaces. Le reste du texte doit correspondre à la réponse de la carte.</p>{account && <div className="account-actions"><button className="secondary-button" onClick={account.changePassword}>Changer mon mot de passe</button><button className="secondary-button" onClick={account.logout}>Se déconnecter</button></div>}<div className="danger-zone"><strong>Repartir de zéro</strong><p>Recommence l’ensemble et efface la progression de cette version web.</p><button className="reset-button" onClick={() => setModal('reset')}><RotateCcw size={16} /> Réinitialiser la progression</button></div></Modal>}
    {modal === 'reset' && <Modal title="Une nouvelle page ?" onClose={closeModal}><p className="modal-description">Les réponses, la maîtrise et les révisions sauvegardées dans cette version web seront effacées. Tu recommenceras au premier groupe.</p><div className="modal-actions"><button className="secondary-button" onClick={() => setModal('settings')}>Garder ma progression</button><button className="danger-button" disabled={busy} onClick={() => void act({ type: 'reset' })}>Recommencer</button></div>{error && <p role="alert">{error}</p>}</Modal>}
    {modal === 'group' && <Modal title={`${groupTitle} · Les cartes`} onClose={closeModal}><p className="modal-description">Les cartes de ta phase actuelle, avec leur état d’apprentissage.</p><ul className="group-cards">{study.active_cards.map(card => <li key={card.id}><span className={`group-state-dot state-${card.state.toLowerCase()}`} /><strong>{card.term}</strong><span>{stateLabels[card.state]}</span></li>)}</ul><p className="modal-footnote">Le moteur favorise les cartes les moins solides et espace les répétitions. Les groupes suivants s’ouvrent une fois celui-ci maîtrisé.</p></Modal>}
  </div>
}
