import { ValidationSidebar, useValidationJobs } from './ValidationJobs'
import type { ValidationDetail } from './ValidationJobs'
import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowRight, BookOpen, ChevronDown, Flower2, Layers3, LibraryBig, LockKeyhole, LogOut, Plus, Search, Settings2, Sprout, Users, X } from 'lucide-react'
import App from './App'
import Dialog from './Dialog'
import SetDetail from './SetDetail'
import { useAccount } from './AuthGate'
import { readLibrary } from './libraryApi'
import type { CardSet, CardSetDetail, SetSelection } from './types'
import './library.css'

type Library = { enabled: boolean; default_set_id?: string; sets: CardSet[] }
type Route = { screen: 'library' } | { screen: 'new'; jobId?: string } | { screen: 'set' | 'study'; id: string; version?: number }

function getRoute(): Route {
  const parts = window.location.hash.slice(1).split('/')
  if (parts[0] === 'new') return { screen: 'new', jobId: parts[1] }
  if ((parts[0] === 'sets' || parts[0] === 'study') && parts[1]) {
    const version = Number(parts[2])
    return { screen: parts[0] === 'sets' ? 'set' : 'study', id: parts[1], version: Number.isSafeInteger(version) && version > 0 ? version : undefined }
  }
  return { screen: 'library' }
}
function routeHash(route: Route) {
  return route.screen === 'library' ? '' : route.screen === 'new' ? `#new${route.jobId ? `/${route.jobId}` : ''}` : `#${route.screen === 'set' ? 'sets' : 'study'}/${route.id}${route.version ? `/${route.version}` : ''}`
}
const detailKey = (route: Route) => route.screen === 'set' ? `${route.id}:${route.version || 'latest'}` : ''

function SetLibrary({ library, recent, open, create, study }: {
  library: Library; recent: SetSelection | null; open: (deck: CardSet) => void; create: () => void; study: (selection: SetSelection) => void
}) {
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<'all' | 'private' | 'shared'>('all')
  const [sort, setSort] = useState('recent')
  const query = search.trim().toLocaleLowerCase('fr')
  const decks = library.sets.filter(deck => `${deck.title} ${deck.description}`.toLocaleLowerCase('fr').includes(query) && (filter === 'all' || (filter === 'shared' ? deck.shared : !deck.shared)))
  if (sort === 'title') decks.sort((a, b) => a.title.localeCompare(b.title, 'fr'))
  if (sort === 'cards') decks.sort((a, b) => (b.versions.at(-1)?.card_count || 0) - (a.versions.at(-1)?.card_count || 0))
  const cardCount = library.sets.reduce((sum, deck) => sum + (deck.versions.at(-1)?.card_count || 0), 0)
  const recentDeck = recent && library.sets.find(deck => deck.id === recent.id && deck.versions.some(version => version.version === recent.version))

  return <>
    <div className="collection-heading">
      <div><div className="collection-eyebrow"><span />TA BIBLIOTHÈQUE</div><h1>Mes ensembles<span>.</span></h1></div>
      {library.enabled && <button className="primary-button" onClick={create}><Plus size={18} />Nouvel ensemble</button>}
    </div>
    <div className="collection-summary"><span><Layers3 size={16} /><strong>{library.sets.length}</strong> ensemble{library.sets.length > 1 ? 's' : ''}</span><span className="summary-separator" /><span><BookOpen size={16} /><strong>{cardCount}</strong> carte{cardCount > 1 ? 's' : ''}</span><span className="collection-summary-note"><Sprout size={15} />À ton rythme.</span></div>
    {recentDeck && recent && <button className="resume-session" onClick={() => study({ ...recent, title: recentDeck.title })}><span className="resume-icon"><BookOpen size={23} /></span><span className="resume-copy"><span>POURSUIVRE L’APPRENTISSAGE</span><strong>{recentDeck.title}</strong><small>Version {recent.version} · Ta progression t’attend.</small></span><span className="resume-action">Reprendre<ArrowRight size={18} /></span></button>}
    <div className="collection-toolbar">
      <div className="collection-filters" aria-label="Filtrer les ensembles">{([{ id: 'all', label: 'Tous les ensembles' }, { id: 'private', label: 'Personnels' }, { id: 'shared', label: 'Partagés' }] as const).map(item => <button key={item.id} className={filter === item.id ? 'selected' : ''} aria-pressed={filter === item.id} onClick={() => setFilter(item.id)}>{item.label}{item.id === 'all' && <span>{library.sets.length}</span>}</button>)}</div>
      <label className="collection-search"><Search size={17} /><input aria-label="Rechercher un ensemble" placeholder="Rechercher un ensemble…" value={search} onChange={event => setSearch(event.target.value)} />{search && <button className="icon-button" aria-label="Effacer la recherche d’ensembles" onClick={() => setSearch('')}><X size={15} /></button>}</label>
    </div>
    <div className="collection-list-heading"><h2>{query ? `Résultats pour « ${search.trim()} »` : filter === 'private' ? 'Tes ensembles personnels' : filter === 'shared' ? 'Les ensembles partagés' : 'Tous tes ensembles'}<span>{decks.length}</span></h2><label className="collection-sort"><span className="sr-only">Trier les ensembles</span><select aria-label="Trier les ensembles" value={sort} onChange={event => setSort(event.target.value)}><option value="recent">Les plus récents</option><option value="title">Par titre</option><option value="cards">Nombre de cartes</option></select><ChevronDown size={14} /></label></div>
    <div className="collection-grid">{decks.map((deck, index) => <button className={`collection-tile tone-${index % 4}`} key={deck.id} onClick={() => open(deck)} aria-label={`Ouvrir ${deck.title}`}>
      <div className="collection-tile-cover"><span className="tile-cover-index">{String(index + 1).padStart(2, '0')} / ENSEMBLE</span><div className="tile-cover-art" aria-hidden="true"><Layers3 size={49} strokeWidth={1.15} /></div><span className="tile-card-count">{deck.versions.at(-1)?.card_count || 0} cartes</span></div>
      <div className="collection-tile-body"><span className={`tile-privacy ${deck.shared ? 'shared' : ''}`}>{deck.shared ? <Users size={13} /> : <LockKeyhole size={12} />}{deck.shared ? 'Partagé' : 'Personnel'}</span><h3>{deck.title}</h3><p>{deck.description || ' '}</p><div className="collection-tile-footer"><span>Voir les cartes</span><ArrowRight size={18} /></div></div>
    </button>)}
      {library.enabled && !query && filter !== 'shared' && <button className="collection-create-tile" onClick={create}><span className="create-tile-icon"><Plus size={27} strokeWidth={1.6} /></span><strong>Une nouvelle idée ?</strong><p>Crée un ensemble de cartes<br />et fais grandir tes connaissances.</p><span>Créer un ensemble<ArrowRight size={15} /></span></button>}
    </div>
    {!decks.length && <div className="collection-empty"><div><Search size={30} strokeWidth={1.4} /></div><h2>{query ? 'Aucun ensemble trouvé.' : 'Une bibliothèque à faire grandir.'}</h2><p>{query ? 'Essaie un autre mot ou un titre différent.' : filter === 'shared' ? 'Les ensembles partagés apparaîtront ici.' : 'Tes ensembles de cartes apparaîtront ici.'}</p>{(query || filter !== 'all') && <button className="secondary-button" onClick={() => { setSearch(''); setFilter('all') }}>Voir tous les ensembles</button>}</div>}
    <div className="collection-footnote"><Flower2 size={15} strokeWidth={1.5} /><span>Une carte à la fois, les idées deviennent des acquis.</span></div>
  </>
}

export default function StudyHome() {
  const account = useAccount()
  const validation = useValidationJobs()
  const [validationDraft, setValidationDraft] = useState<ValidationDetail | null>(null)
  const [library, setLibrary] = useState<Library | null>(null)
  const [route, setRoute] = useState<Route>(getRoute)
  const routeRef = useRef(route)
  routeRef.current = route
  const dirtyRef = useRef(false)
  const [pendingRoute, setPendingRoute] = useState<Route | null>(null)
  const [detail, setDetail] = useState<{ key: string; deck: CardSetDetail } | null>(null)
  const [error, setError] = useState('')
  const [detailError, setDetailError] = useState('')
  const [retry, setRetry] = useState(0)
  const storageKey = `memo:selected-set:${account?.user.username || 'local'}`
  const [recent, setRecent] = useState<SetSelection | null>(() => {
    try { return JSON.parse(localStorage.getItem(storageKey) || 'null') } catch { return null }
  })

  const load = useCallback(async () => {
    try { setLibrary(await readLibrary<Library>('sets')); setError('') }
    catch (caught) { setError((caught as Error).message) }
  }, [])
  useEffect(() => { void load() }, [load])
  const commit = useCallback((next: Route, replace = false) => {
    const url = `${window.location.pathname}${window.location.search}${routeHash(next)}`
    window.history[replace ? 'replaceState' : 'pushState'](null, '', url)
    routeRef.current = next
    setRoute(next); setDetailError('')
    window.scrollTo(0, 0)
  }, [])
  const navigate = useCallback((next: Route) => {
    if (dirtyRef.current) { setPendingRoute(next); return }
    commit(next)
  }, [commit])
  useEffect(() => {
    const open = (event: Event) => {
      const job = (event as CustomEvent<ValidationDetail>).detail
      if (!job.set_id) setValidationDraft(job)
      navigate(job.set_id ? { screen: 'set', id: job.set_id } : { screen: 'new', jobId: job.id })
    }
    window.addEventListener('memo:open-validation', open)
    return () => window.removeEventListener('memo:open-validation', open)
  }, [navigate])
  useEffect(() => {
    if (route.screen === 'new' && route.jobId && validationDraft?.id !== route.jobId) validation.review(route.jobId)
  }, [route.screen === 'new' ? route.jobId : undefined])
  useEffect(() => {
    if (route.screen === 'new' && route.jobId && validation.selected?.id === route.jobId && validationDraft?.id !== route.jobId) {
      setValidationDraft(validation.selected)
    }
  }, [route.screen === 'new' ? route.jobId : undefined, validation.selected, validationDraft?.id])
  const onDirty = useCallback((dirty: boolean) => { dirtyRef.current = dirty }, [])
  useEffect(() => {
    const changed = () => {
      const next = getRoute()
      if (dirtyRef.current) {
        window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}${routeHash(routeRef.current)}`)
        setPendingRoute(next)
      } else { routeRef.current = next; setRoute(next); setDetailError(''); window.scrollTo(0, 0) }
    }
    window.addEventListener('hashchange', changed)
    return () => window.removeEventListener('hashchange', changed)
  }, [])
  const key = detailKey(route)
  useEffect(() => {
    if (route.screen !== 'set' || !library || detail?.key === key) return
    let cancelled = false
    setDetailError('')
    void readLibrary<CardSetDetail>(`sets/${route.id}${route.version ? `?version=${route.version}` : ''}`).then(deck => {
      if (!cancelled) setDetail({ key, deck })
    }).catch(caught => { if (!cancelled) setDetailError((caught as Error).message) })
    return () => { cancelled = true }
  }, [route, library, detail?.key, key, retry])
  useEffect(() => {
    const title = route.screen === 'library' ? 'Mes ensembles' : route.screen === 'new' ? 'Nouvel ensemble' : library?.sets.find(deck => deck.id === route.id)?.title || 'Ensemble'
    document.title = `${title} · mémo`
  }, [route, library])

  const home = () => { navigate({ screen: 'library' }); void load() }
  const startStudy = (selection: SetSelection) => {
    setRecent(selection)
    try { localStorage.setItem(storageKey, JSON.stringify(selection)) } catch { /* Studying also works without browser storage. */ }
    navigate({ screen: 'study', id: selection.id, version: selection.version })
  }
  const saveDetail = (deck: CardSetDetail) => {
    dirtyRef.current = false
    setLibrary(current => current && { ...current, sets: [deck, ...current.sets.filter(item => item.id !== deck.id)] })
    setDetail({ key: `${deck.id}:latest`, deck })
    commit({ screen: 'set', id: deck.id }, true)
  }

  if (!library) return <div className="boot-screen"><Flower2 size={34} /><h1>mémo.</h1>{error ? <><p role="alert">{error}</p><button className="primary-button" onClick={() => void load()}>Réessayer</button></> : <p>Ta bibliothèque se prépare…</p>}</div>
  if (route.screen === 'study') {
    const deck = library.sets.find(item => item.id === route.id)
    const selection = { id: route.id, title: deck?.title || 'Mon ensemble', version: route.version || deck?.latest_version || 1 }
    return <App key={`${selection.id}:${selection.version}`} deck={library.enabled ? selection : undefined} onLibrary={home} onSet={() => navigate({ screen: 'set', id: selection.id, version: selection.version === deck?.latest_version ? undefined : selection.version })} />
  }
  const currentDetail = detail?.key === key ? detail.deck : null
  const restoredDraft = route.screen === 'new' && route.jobId
    ? [validationDraft, validation.selected].find(job => job?.id === route.jobId) || null : null

  return <div className="collection-shell">
    <aside className="collection-sidebar">
      <button className="collection-brand" onClick={home} aria-label="Mémo, accueil"><Flower2 size={29} strokeWidth={1.7} /><span>mémo<span>.</span></span></button>
      <nav aria-label="Navigation principale"><span className="collection-nav-label">MON ESPACE</span><button className="collection-nav-item active" onClick={home} aria-label="Mes ensembles" title="Mes ensembles" aria-current={route.screen === 'library' ? 'page' : undefined}><LibraryBig size={19} /><span>Mes ensembles</span><span className="collection-nav-count">{library.sets.length}</span></button>{library.enabled && <button className="collection-nav-item" onClick={() => navigate({ screen: 'new' })} aria-label="Créer un ensemble" title="Créer un ensemble"><Plus size={19} /><span>Créer un ensemble</span></button>}{account && <><button className="collection-nav-item" onClick={account.changePassword} aria-label="Changer mon mot de passe" title="Changer mon mot de passe"><Settings2 size={19} /><span>Changer mon mot de passe</span></button><button className="collection-nav-item" onClick={account.logout} aria-label="Se déconnecter" title="Se déconnecter"><LogOut size={19} /><span>Se déconnecter</span></button></>}</nav>
      <ValidationSidebar />
      <div className="collection-sidebar-footer"><span className="collection-avatar">{account?.user.display_name.charAt(0).toUpperCase() || 'M'}</span><div><strong>{account?.user.display_name || 'Mon espace'}</strong><span>À mon rythme</span></div><Sprout size={17} /></div>
    </aside>
    <div className="collection-workspace">
      <main className="collection-main">
        {error && <div className="detail-error" role="alert"><span>{error}</span><button onClick={() => void load()}>Réessayer</button></div>}
        {route.screen === 'library' ? <SetLibrary library={library} recent={recent} open={deck => navigate({ screen: 'set', id: deck.id })} create={() => navigate({ screen: 'new' })} study={startStudy} /> : route.screen === 'new' && !library.enabled ? <div className="collection-empty"><LockKeyhole size={30} /><h1>La création d’ensembles est indisponible.</h1><p>Ouvre ta bibliothèque connectée pour créer tes cartes.</p><button className="secondary-button" onClick={home}>Revenir à mes ensembles</button></div> : (route.screen === 'new' && (!route.jobId || restoredDraft)) || currentDetail ? <SetDetail key={route.screen === 'new' ? `new:${route.jobId || ''}` : `${currentDetail!.id}:${currentDetail!.version}:${currentDetail!.revision}`} initialValidation={restoredDraft} original={route.screen === 'new' ? null : currentDetail} canCreate={library.enabled} onBack={home} onDirty={onDirty} onSaved={saveDetail} onStudy={deck => startStudy({ id: deck.id, title: deck.title, version: deck.version })} onVersion={version => {
          // A conflict reload also needs to go through the unsaved-edit guard.
          if (route.screen === 'set') { navigate({ screen: 'set', id: route.id, version: version === currentDetail?.latest_version ? undefined : version }); if (!dirtyRef.current) { setDetail(null); setRetry(value => value + 1) } }
        }} /> : <div className="collection-loading" role={detailError ? 'alert' : 'status'}><Layers3 size={32} strokeWidth={1.4} /><h2>{detailError || 'Tes cartes se préparent…'}</h2>{detailError && <div><button className="secondary-button" onClick={home}>Mes ensembles</button><button className="primary-button" onClick={() => setRetry(value => value + 1)}>Réessayer</button></div>}</div>}
      </main>
    </div>
    {pendingRoute && <Dialog title="Modifications non enregistrées" onClose={() => setPendingRoute(null)}><p className="dialog-explanation">Tes modifications n’ont pas encore été enregistrées. Tu peux continuer à modifier tes cartes ou quitter cet ensemble.</p><div className="modal-actions"><button className="secondary-button" onClick={() => setPendingRoute(null)}>Continuer à modifier</button><button className="primary-button" onClick={() => { dirtyRef.current = false; setDetail(null); commit(pendingRoute); setPendingRoute(null) }}>Quitter sans enregistrer<ArrowRight size={16} /></button></div></Dialog>}
  </div>
}
