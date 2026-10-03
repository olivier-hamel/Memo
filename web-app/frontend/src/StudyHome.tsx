import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, ArrowRight, BookOpen, Flower2, Layers3, Pencil, Plus, Trash2 } from 'lucide-react'
import App from './App'
import { useAccount } from './AuthGate'
import { apiFetch } from './api'
import type { CardInput, CardSet, CardSetDetail, SetSelection } from './types'

async function read<T>(path: string, body?: unknown): Promise<T> {
  const response = await apiFetch(path, body === undefined ? { cache: 'no-store' } : { method: 'POST', body: JSON.stringify(body) })
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Vérifie les informations saisies.')
  return data as T
}

type Library = { enabled: boolean; default_set_id?: string; sets: CardSet[] }
const blankCard = (): CardInput => ({ term: '', definition: '' })

function SetEditor({ original, saved, cancel }: { original: CardSetDetail | null; saved: (deck: CardSetDetail) => void; cancel: () => void }) {
  const [title, setTitle] = useState(original?.title || '')
  const [description, setDescription] = useState(original?.description || '')
  const [cards, setCards] = useState<CardInput[]>(original?.cards || [blankCard()])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  return <form className="set-editor" onSubmit={async event => {
    event.preventDefault()
    if (busy) return
    setBusy(true); setError('')
    try {
      saved(await read<CardSetDetail>(original ? `sets/${original.id}` : 'sets', {
        title, description, cards, revision: original?.revision,
      }))
    } catch (caught) { setError((caught as Error).message) }
    finally { setBusy(false) }
  }}>
    <div className="library-heading"><div><span className="eyebrow">UN ENSEMBLE À TON IMAGE</span><h1>{original ? 'Affiner tes cartes.' : 'Une nouvelle idée à cultiver.'}</h1></div><button className="secondary-button" type="button" onClick={cancel} disabled={busy}>Annuler</button></div>
    <p className="library-intro">{original ? 'Modifier les questions ou les réponses crée une nouvelle version. Tes acquis restent disponibles dans les versions précédentes.' : 'Ton nouvel ensemble est privé. Ajoute des questions claires et les réponses que tu souhaites retenir.'}</p>
    {error && <div className="auth-error" role="alert">{error}</div>}
    <fieldset disabled={busy}>
      <label>Titre de l’ensemble<input value={title} onChange={event => setTitle(event.target.value)} required maxLength={100} /></label>
      <label>Description <span>(facultative)</span><textarea value={description} onChange={event => setDescription(event.target.value)} maxLength={1000} rows={2} /></label>
      <div className="editor-cards">
        {cards.map((card, index) => <section className="editor-card" key={index} aria-label={`Carte ${index + 1}`}>
          <div className="editor-card-heading"><strong>Carte {index + 1}</strong><button className="icon-button" type="button" aria-label={`Supprimer la carte ${index + 1}`} disabled={cards.length === 1} onClick={() => setCards(current => current.filter((_, i) => i !== index))}><Trash2 size={16} /></button></div>
          <label>Question {index + 1}<textarea value={card.term} required maxLength={2000} rows={2} onChange={event => setCards(current => current.map((c, i) => i === index ? { ...c, term: event.target.value } : c))} /></label>
          <label>Réponse {index + 1}<textarea value={card.definition} required maxLength={12000} rows={3} onChange={event => setCards(current => current.map((c, i) => i === index ? { ...c, definition: event.target.value } : c))} /></label>
        </section>)}
      </div>
      <button className="secondary-button add-card" type="button" disabled={cards.length >= 300} onClick={() => setCards(current => [...current, blankCard()])}><Plus size={16} /> Ajouter une carte</button>
      <div className="editor-footer"><span>{cards.length} carte{cards.length > 1 ? 's' : ''}</span><button className="primary-button" type="submit">{busy ? 'Enregistrement…' : 'Enregistrer l’ensemble'}<ArrowRight size={17} /></button></div>
    </fieldset>
  </form>
}

export default function StudyHome() {
  const account = useAccount()
  const [library, setLibrary] = useState<Library | null>(null)
  const [selection, setSelection] = useState<SetSelection | null>(null)
  const [screen, setScreen] = useState<'study' | 'library' | 'editor'>('study')
  const [original, setOriginal] = useState<CardSetDetail | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const storageKey = `memo:selected-set:${account?.user.username || 'local'}`

  const load = useCallback(async () => {
    try {
      const data = await read<Library>('sets')
      setLibrary(data); setError('')
    } catch (caught) { setError((caught as Error).message) }
  }, [])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!library?.enabled || selection) return
    let saved: SetSelection | null = null
    try { saved = JSON.parse(localStorage.getItem(storageKey) || 'null') } catch { /* First visit or unavailable storage. */ }
    const matching = saved && library.sets.find(deck => deck.id === saved!.id && deck.versions.some(v => v.version === saved!.version))
    const defaultSet = library.sets.find(deck => deck.id === library.default_set_id)
    if (matching && saved) setSelection({ id: matching.id, title: matching.title, version: saved.version })
    else if (defaultSet) setSelection({ id: defaultSet.id, title: defaultSet.title, version: 1 })
    else setScreen('library')
  }, [library, selection, storageKey])

  const select = (deck: CardSet, version: number) => {
    const chosen = { id: deck.id, title: deck.title, version }
    setSelection(chosen); setScreen('study'); setError('')
    try { localStorage.setItem(storageKey, JSON.stringify(chosen)) } catch { /* Selection still works without local storage. */ }
  }
  const edit = async (deck: CardSet) => {
    if (busy) return
    setBusy(true); setError('')
    try { setOriginal(await read<CardSetDetail>(`sets/${deck.id}`)); setScreen('editor') }
    catch (caught) { setError((caught as Error).message) }
    finally { setBusy(false) }
  }
  if (!library) return <div className="boot-screen"><Flower2 size={34} /><h1>mémo.</h1>{error ? <><p role="alert">{error}</p><button className="primary-button" onClick={() => void load()}>Réessayer</button></> : <p>Ta bibliothèque se prépare…</p>}</div>
  if (!library.enabled) return <App />
  if (screen === 'study' && selection) return <App key={`${selection.id}:${selection.version}`} deck={selection} onLibrary={() => { setScreen('library'); void load() }} />
  return <div className="library-shell">
    <header className="library-topbar"><span className="library-brand"><Flower2 size={27} /> mémo.</span><span>{account?.user.display_name}</span>{selection && <button className="secondary-button" onClick={() => setScreen('study')} disabled={busy}><ArrowLeft size={15} /> Revenir aux cartes</button>}</header>
    <main className="library-main">
      {screen === 'editor' ? <SetEditor key={original ? `${original.id}:${original.revision}` : 'new'} original={original} cancel={() => setScreen('library')} saved={deck => {
        void load()
        select(deck, deck.latest_version)
      }} /> : <>
        <div className="library-heading"><div><span className="eyebrow">TON SAVOIR PREND RACINE</span><h1>Mes ensembles.</h1></div><button className="primary-button" onClick={() => { setOriginal(null); setScreen('editor'); setError('') }}><Plus size={17} /> Nouvel ensemble</button></div>
        <p className="library-intro">Choisis un ensemble pour reprendre ou crée tes propres cartes. Chaque version garde sa progression.</p>
        {error && <div className="auth-error" role="alert">{error}<button className="auth-secondary" onClick={() => void load()}>Réessayer</button></div>}
        {!library.sets.length && <div className="library-empty"><Layers3 size={34} /><p>Un peu de place pour tes prochaines idées.</p></div>}
        <div className="set-grid">{library.sets.map(deck => <section className="set-tile" key={deck.id} aria-label={deck.title}>
          <div className="set-tile-top"><BookOpen size={23} /><span>{deck.shared ? 'Ensemble partagé' : 'Mon ensemble privé'}</span></div>
          <h2>{deck.title}</h2><p>{deck.description}</p>
          <div className="set-versions"><span>{deck.versions.at(-1)?.card_count} cartes · Version {deck.latest_version}</span></div>
          <div className="set-tile-actions"><button className="primary-button" disabled={busy} onClick={() => select(deck, deck.latest_version)}>Apprendre<ArrowRight size={15} /></button>{deck.editable && <button className="secondary-button" disabled={busy} onClick={() => void edit(deck)} aria-label={`Modifier ${deck.title}`}><Pencil size={15} /> Modifier</button>}</div>
          {deck.versions.length > 1 && <label className="older-version">Reprendre une version précédente<select aria-label={`Version de ${deck.title}`} value="" onChange={event => select(deck, Number(event.target.value))}><option value="" disabled>Choisir une version</option>{deck.versions.slice(0, -1).map(v => <option key={v.version} value={v.version}>Version {v.version} · {v.card_count} cartes</option>)}</select></label>}
        </section>)}</div>
      </>}
    </main>
  </div>
}
