import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { KeyboardEvent, TextareaHTMLAttributes } from 'react'
import { ArrowLeft, ArrowRight, BookOpen, Check, CheckCircle2, Cloud, Download, Layers3, Link, LoaderCircle, LockKeyhole, Pencil, Plus, Save, Search, Trash2, Undo2, X } from 'lucide-react'
import type { CardInput, CardSetDetail, ReferenceDocument } from './types'
import { LibraryError, readLibrary } from './libraryApi'
import DocumentWorkspace from './DocumentWorkspace'
import { useValidationJobs } from './ValidationJobs'
import type { ValidationDetail } from './ValidationJobs'

type DraftCard = CardInput & { key: string }
const draftCard = (card: CardInput = { term: '', definition: '' }): DraftCard => ({ ...card, key: crypto.randomUUID() })
const cardInputs = (cards: DraftCard[]) => cards.map(({ term, definition }) => ({ term, definition }))

function GrowingTextarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useLayoutEffect(() => {
    const field = ref.current!
    const resize = () => { field.style.height = '0px'; field.style.height = `${field.scrollHeight + 2}px` }
    resize()
    // Only width changes need to recalculate wrapping.
    let width = field.getBoundingClientRect().width
    const widthObserver = new ResizeObserver(entries => {
      const next = entries[0].contentRect.width
      if (next !== width) { width = next; resize() }
    })
    widthObserver.observe(field)
    return () => widthObserver.disconnect()
  }, [props.value])
  return <textarea {...props} ref={ref} rows={1} />
}

export default function SetDetail({ original, initialValidation, canCreate, onBack, onSaved, onStudy, onVersion, onDirty }: {
  original: CardSetDetail | null
  initialValidation?: ValidationDetail | null
  canCreate: boolean
  onBack: () => void
  onSaved: (deck: CardSetDetail) => void
  onStudy: (deck: CardSetDetail) => void
  onVersion: (version: number) => void
  onDirty: (dirty: boolean) => void
}) {
  const validation = useValidationJobs()
  const [draftId] = useState(() => initialValidation?.draft_id || crypto.randomUUID())
  const [title, setTitle] = useState(original?.title || initialValidation?.snapshot.title || '')
  const [description, setDescription] = useState(original?.description || initialValidation?.snapshot.description || '')
  const [cards, setCards] = useState<DraftCard[]>(() => (original?.cards || initialValidation?.snapshot.cards || [{ term: '', definition: '' }]).map(draftCard))
  const [documents, setDocuments] = useState<ReferenceDocument[]>(original?.documents || initialValidation?.documents || [])
  const [uploadingDocuments, setUploadingDocuments] = useState(false)
  const [saving, setBusy] = useState(false)
  const [importing, setImporting] = useState(false)
  const [launchingValidation, setLaunchingValidation] = useState(false)
  const busy = saving || importing || launchingValidation
  const validating = validation.jobs.some(job => (job.set_id === original?.id || (!job.set_id && job.draft_id === draftId)) && (job.status === 'queued' || job.status === 'running'))
  const [importOpen, setImportOpen] = useState(false)
  const [quizletUrl, setQuizletUrl] = useState('')
  const [importError, setImportError] = useState('')
  const [importNotice, setImportNotice] = useState('')
  const pending = useRef(false)
  const [error, setError] = useState('')
  const [conflict, setConflict] = useState(false)
  const [savedNotice, setSavedNotice] = useState(false)
  const [search, setSearch] = useState('')
  const [removed, setRemoved] = useState<{ card: DraftCard; index: number } | null>(null)
  const [newCardKey, setNewCardKey] = useState('')
  const form = useRef<HTMLFormElement>(null)
  const latest = !original || original.version === original.latest_version
  const editable = original ? original.editable && latest : canCreate
  const originalValue = JSON.stringify({ title: original?.title || '', description: original?.description || '', cards: original?.cards || [{ term: '', definition: '' }], document_ids: (original?.documents || []).map(document => document.id) })
  const dirty = editable && JSON.stringify({ title, description, cards: cardInputs(cards), document_ids: documents.map(document => document.id) }) !== originalValue
  const query = search.trim().toLocaleLowerCase('fr')
  const visible = cards.map((card, index) => ({ card, index })).filter(({ card }) => `${card.term} ${card.definition}`.toLocaleLowerCase('fr').includes(query))

  useEffect(() => { onDirty(dirty || importing || uploadingDocuments) }, [dirty, importing, uploadingDocuments, onDirty])
  useEffect(() => {
    if (!dirty && !importing && !uploadingDocuments) return
    const prevent = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', prevent)
    return () => window.removeEventListener('beforeunload', prevent)
  }, [dirty, importing, uploadingDocuments])
  useLayoutEffect(() => {
    if (newCardKey) form.current?.querySelector<HTMLTextAreaElement>(`[data-card-key="${newCardKey}"] textarea`)?.focus()
  }, [newCardKey])

  useEffect(() => {
    if (!editable) return
    validation.register({ key: original?.id || draftId, cards: cardInputs(cards.filter(card => card.term.trim() || card.definition.trim())), accept: accepted => {
      setCards(current => [...current.filter(card => card.term.trim() || card.definition.trim()), ...accepted.map(draftCard)])
      setSearch(''); setSavedNotice(false)
    } })
    return () => validation.register(null)
  }, [cards, editable, original?.id, draftId, validation.register])
  const startValidation = async () => {
    if (launchingValidation || validating || busy || uploadingDocuments) return
    const values = cardInputs(cards.filter(card => card.term.trim() || card.definition.trim()))
    if (!documents.length) { setError('Ajoute au moins un document de cours pour valider tes cartes.'); return }
    if (!values.length || values.some(card => !card.term.trim() || !card.definition.trim())) {
      setError('Complète le terme et la définition de chaque carte avant la validation.'); return
    }
    setLaunchingValidation(true); setError('')
    try {
      await validation.start({ title: title.trim() || 'Mon ensemble', description, set_id: original?.id || null,
        draft_id: draftId, cards: values, document_ids: documents.map(document => document.id) })
    } catch (caught) { setError((caught as Error).message) }
    finally { setLaunchingValidation(false) }
  }
  const update = (key: string, field: keyof CardInput, value: string) => {
    setCards(current => current.map(card => card.key === key ? { ...card, [field]: value } : card))
    setSavedNotice(false)
  }
  const save = async (studyAfter = false) => {
    if (pending.current || launchingValidation || uploadingDocuments || !editable || !form.current?.reportValidity()) return
    const values = cardInputs(cards.filter(card => card.term.trim() || card.definition.trim()))
    if (!values.length) {
      setError('Ajoute au moins une carte avec un terme et une définition.'); return
    }
    if (!title.trim() || values.some(card => !card.term.trim() || !card.definition.trim())) {
      setError('Ajoute un titre, un terme et une définition pour chaque carte.'); return
    }
    if (new Set(values.map(card => JSON.stringify(card))).size !== values.length) {
      setError('Deux cartes identiques sont présentes dans cet ensemble. Modifie ou supprime le doublon.'); return
    }
    pending.current = true
    setBusy(true); setError(''); setConflict(false)
    try {
      const deck = await readLibrary<CardSetDetail>(original ? `sets/${original.id}` : 'sets', {
        title, description, cards: values, revision: original?.revision, document_ids: documents.map(document => document.id),
      })
      onDirty(false)
      setRemoved(null); setSavedNotice(true)
      if (!original && validation.jobs.some(job => job.draft_id === draftId)) {
        try { await validation.link(draftId, deck.id) }
        catch { /* The saved set is safe; the original validation draft remains reviewable. */ }
      }
      onSaved(deck)
      if (studyAfter) onStudy(deck)
    } catch (caught) {
      setError((caught as Error).message)
      setConflict(caught instanceof LibraryError && caught.status === 409)
    } finally { pending.current = false; setBusy(false) }
  }
  const study = () => {
    if (dirty || !original) void save(true)
    else onStudy(original)
  }
  const add = () => {
    if (busy || cards.length >= 300) return
    const card = draftCard()
    setCards(current => [...current, card]); setSearch(''); setNewCardKey(card.key); setSavedNotice(false)
  }
  const importCards = async () => {
    if (pending.current || !editable || original) return
    if (!quizletUrl.trim()) { setImportError('Colle le lien d’un ensemble public Quizlet.'); return }
    pending.current = true
    setImporting(true); setImportError(''); setImportNotice(''); setError('')
    try {
      const imported = await readLibrary<{ title: string; description: string; cards: CardInput[] }>('sets/import/quizlet', { url: quizletUrl.trim() })
      // Preserve even partially filled draft cards; only discard empty placeholders.
      const existing = cards.filter(card => card.term.trim() || card.definition.trim())
      const combined = [...existing, ...imported.cards.map(draftCard)]
      if (combined.length > 300) throw new Error('L’import dépasserait la limite de 300 cartes. Réduis ton brouillon ou choisis un ensemble plus petit.')
      if (new Set(combined.map(card => JSON.stringify({ term: card.term, definition: card.definition }))).size !== combined.length) {
        throw new Error('L’import contient des cartes déjà présentes dans ton brouillon. Retire ces doublons avant de réessayer.')
      }
      setCards(combined)
      if (!title.trim()) setTitle(imported.title)
      if (!description.trim()) setDescription(imported.description)
      setRemoved(null); setSearch(''); setSavedNotice(false)
      setImportNotice(`${imported.cards.length} carte${imported.cards.length > 1 ? 's importées' : ' importée'}. Vérifie les textes, puis crée ton ensemble.`)
      setImportOpen(false)
    } catch (caught) {
      setImportError((caught as Error).message)
    } finally { pending.current = false; setImporting(false) }
  }
  const addOnEnter = (event: KeyboardEvent<HTMLTextAreaElement>, card: DraftCard) => {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing || !card.term.trim() || !card.definition.trim()) return
    event.preventDefault()
    if (!event.repeat) add()
  }

  return <form ref={form} className="set-detail" onSubmit={event => { event.preventDefault(); void save() }}>
    <DocumentWorkspace documents={documents} onDocuments={setDocuments} editable={editable} disabled={busy} setId={original?.id} onUploading={setUploadingDocuments} header={<>
    <button className="back-to-library" type="button" onClick={onBack} disabled={busy}><ArrowLeft size={16} /> Mes ensembles</button>
    <div className="set-detail-heading">
      <div className="set-detail-title">
        <div className="detail-kicker"><Layers3 size={15} /><span>{original ? original.shared ? 'ENSEMBLE PARTAGÉ' : 'MON ENSEMBLE' : 'NOUVEL ENSEMBLE'}</span>{original && <span className="version-badge">Version {original.version}</span>}</div>
        {editable ? <>
          <label className="sr-only" htmlFor="set-title">Titre de l’ensemble</label>
          <input id="set-title" className="set-title-input" value={title} placeholder="Donne un titre à ton ensemble" required maxLength={100} disabled={busy} onChange={event => { setTitle(event.target.value); setSavedNotice(false) }} />
          <label className="sr-only" htmlFor="set-description">Description (facultative)</label>
          <GrowingTextarea id="set-description" className="set-description-input" value={description} placeholder="Ajoute une description (facultative)" maxLength={1000} disabled={busy} onChange={event => { setDescription(event.target.value); setSavedNotice(false) }} />
        </> : <><h1>{title}</h1>{description && <p className="set-description-readonly">{description}</p>}</>}
        <div className="set-detail-meta"><span>{cards.length} carte{cards.length > 1 ? 's' : ''}</span><span className="meta-dot" />{editable ? <span><Pencil size={13} /> Clique sur un texte pour le modifier</span> : <span><LockKeyhole size={13} /> Lecture seule</span>}</div>
      </div>
      <div className="detail-heading-actions">
        {editable && <button className="secondary-button detail-save" type="submit" disabled={busy || uploadingDocuments || (!!original && !dirty)}><Save size={16} />{saving ? 'Enregistrement…' : original ? 'Enregistrer' : 'Créer l’ensemble'}</button>}
        {editable && <button className="secondary-button" type="button" disabled={busy || uploadingDocuments || launchingValidation || validating} onClick={() => void startValidation()}><CheckCircle2 size={16} /> {validating ? 'Validation en cours…' : launchingValidation ? 'Lancement…' : 'Validation'}</button>}
        {original && <button className="primary-button" type="button" onClick={study} disabled={busy || uploadingDocuments}><BookOpen size={18} />{dirty ? 'Enregistrer et étudier' : 'Étudier cet ensemble'}<ArrowRight size={16} /></button>}
      </div>
    </div>

    {!latest && <div className="detail-notice"><Layers3 size={17} /><span>Tu consultes une version précédente. Sa progression est conservée.</span><button type="button" onClick={() => onVersion(original!.latest_version)}>Voir la version actuelle<ArrowRight size={14} /></button></div>}
    {error && <div className="detail-error" role="alert"><span>{error}</span>{conflict && <button type="button" onClick={() => onVersion(original!.version)}>Recharger l’ensemble</button>}</div>}

    {editable && !original && <section className="quizlet-import" aria-label="Import Quizlet" aria-busy={importing}>
      <button className="quizlet-import-toggle" type="button" disabled={busy} aria-expanded={importOpen} aria-controls="quizlet-import-panel" onClick={() => { setImportOpen(!importOpen); setImportError('') }}><Download size={17} /><span>Importer depuis Quizlet</span><Plus size={16} className={importOpen ? 'is-open' : ''} /></button>
      {importOpen && <div id="quizlet-import-panel" className="quizlet-import-panel">
        <p>Colle un lien public pour remplir tes cartes. Les cartes déjà saisies seront conservées.</p>
        <label htmlFor="quizlet-url">Lien public Quizlet</label>
        <div className="quizlet-import-fields"><div className="quizlet-url-field"><Link size={16} /><input id="quizlet-url" inputMode="url" autoComplete="off" placeholder="https://quizlet.com/123456/mon-ensemble-flash-cards/" maxLength={2048} value={quizletUrl} disabled={busy} aria-describedby="quizlet-import-help" onChange={event => { setQuizletUrl(event.target.value); setImportError('') }} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); void importCards() } }} /></div>
          <button className="secondary-button" type="button" disabled={busy || !quizletUrl.trim()} onClick={() => void importCards()}>{importing ? <LoaderCircle size={16} className="import-spinner" /> : <Download size={16} />}{importing ? 'Import en cours…' : 'Importer les cartes'}</button>
        </div>
        {importing && <p role="status">Lecture de la page et extraction des cartes… Cela peut prendre une minute.</p>}
        {importError && <div className="detail-error" role="alert">{importError}</div>}
      </div>}
      {importNotice && <p className="quizlet-import-notice" role="status"><CheckCircle2 size={17} />{importNotice}</p>}
    </section>}

    </>}>
    <section className="card-list-section" aria-labelledby="card-list-heading">
      <div className="card-list-toolbar">
        <div className="card-list-heading"><h2 id="card-list-heading">Les cartes</h2><span>{query ? `${visible.length} / ${cards.length}` : cards.length}</span></div>
        <div className="card-list-tools">
          <label className="list-search"><Search size={16} /><input aria-label="Rechercher une carte" placeholder="Rechercher une carte" value={search} onChange={event => setSearch(event.target.value)} disabled={busy} />{search && <button className="icon-button" type="button" aria-label="Effacer la recherche de cartes" onClick={() => setSearch('')}><X size={14} /></button>}</label>
          {original && original.versions.length > 1 && <label className="version-select"><Layers3 size={15} /><select aria-label={`Version de ${original.title}`} value={original.version} disabled={dirty || busy} onChange={event => onVersion(Number(event.target.value))}>{original.versions.slice().reverse().map(version => <option key={version.version} value={version.version}>Version {version.version}{version.version === original.latest_version ? ' · actuelle' : ''}</option>)}</select></label>}
        </div>
      </div>
      <div className="card-row-labels" aria-hidden="true"><span /><span>TERME</span><span>DÉFINITION</span><span /></div>
      <div className={`card-list ${editable ? 'is-editable' : ''}`}>
        {visible.map(({ card, index }) => <section className="card-row" key={card.key} data-card-key={card.key} aria-label={`Carte ${index + 1}`}>
          <span className="card-row-number">{String(index + 1).padStart(2, '0')}</span>
          <div className="card-row-term">
            {editable ? <label><span className="sr-only">Terme {index + 1}</span><GrowingTextarea aria-label={`Terme ${index + 1}`} value={card.term} maxLength={2000} placeholder="Saisis un terme" disabled={busy} onChange={event => update(card.key, 'term', event.target.value)} onKeyDown={event => addOnEnter(event, card)} /></label> : <p>{card.term}</p>}
          </div>
          <div className="card-row-definition">
            {editable ? <label><span className="sr-only">Définition {index + 1}</span><GrowingTextarea aria-label={`Définition ${index + 1}`} value={card.definition} maxLength={12000} placeholder="Ajoute une définition" disabled={busy} onChange={event => update(card.key, 'definition', event.target.value)} onKeyDown={event => addOnEnter(event, card)} /></label> : <p>{card.definition}</p>}
          </div>
          {editable ? <button className="icon-button delete-card" type="button" aria-label={`Supprimer la carte ${index + 1}`} title={cards.length === 1 ? 'Conserve au moins une carte' : 'Supprimer cette carte'} disabled={busy || cards.length === 1} onClick={() => {
            setRemoved({ card, index }); setCards(current => current.filter(item => item.key !== card.key)); setSavedNotice(false)
          }}><Trash2 size={17} /></button> : <span />}
        </section>)}
      </div>
      {!visible.length && <div className="no-card-results"><Search size={24} /><h3>Aucune carte trouvée</h3><p>Essaie un autre terme ou une partie de la définition.</p><button className="secondary-button" type="button" onClick={() => setSearch('')}>Afficher toutes les cartes</button></div>}
      {editable && <button className="add-card-row" type="button" disabled={busy || cards.length >= 300} onClick={add}><span><Plus size={21} /></span>Ajouter une carte<small>{cards.length >= 300 ? 'Limite de 300 cartes atteinte' : `${cards.length} / 300`}</small></button>}
    </section>
    {editable && <div className="detail-savebar">
      <div className={`detail-save-status ${dirty ? 'has-changes' : ''}`} role="status" aria-live="polite">{busy ? <Cloud size={17} /> : dirty || !original ? <span className="unsaved-dot" /> : <CheckCircle2 size={17} />}<span>{importing ? 'Import des cartes Quizlet…' : saving ? 'Enregistrement de ton ensemble…' : dirty ? 'Modifications non enregistrées' : savedNotice ? 'Toutes les modifications sont enregistrées' : original ? 'Toutes les modifications sont enregistrées' : 'Ton ensemble est prêt à prendre forme'}</span></div>
      <div className="detail-save-actions"><button className="secondary-button" type="button" disabled={busy || uploadingDocuments || launchingValidation || validating} onClick={() => void startValidation()}><CheckCircle2 size={17} /> {validating ? 'Validation en cours…' : launchingValidation ? 'Lancement…' : 'Validation'}</button>
      <button className="primary-button" type="submit" disabled={busy || uploadingDocuments || (!!original && !dirty)}>{saving ? 'Enregistrement…' : original ? 'Enregistrer les modifications' : 'Créer l’ensemble'}<Check size={17} /></button></div>
    </div>}
    {removed && <div className="undo-toast" role="status"><Trash2 size={16} /><span>Carte supprimée</span><button type="button" disabled={busy || cards.length >= 300} onClick={() => {
      setCards(current => { const next = [...current]; next.splice(Math.min(removed.index, next.length), 0, removed.card); return next })
      setSearch(''); setRemoved(null)
    }}><Undo2 size={15} />Annuler</button><button className="icon-button" type="button" aria-label="Fermer la notification" onClick={() => setRemoved(null)}><X size={14} /></button></div>}
    </DocumentWorkspace>
  </form>
}
