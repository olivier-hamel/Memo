import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Bell, CheckCircle2, LoaderCircle, X } from 'lucide-react'
import { apiFetch } from './api'
import { useAccount } from './AuthGate'
import CardValidationDialog from './CardValidationDialog'
import type { CardInput, ReferenceDocument } from './types'

type Proposal = CardInput & { document_id: string; page: number; evidence: string; missing_information: string }
export type ValidationSnapshot = { title: string; description: string; set_id: string | null; draft_id: string; cards: CardInput[]; document_ids: string[] }
export type ValidationJob = { id: string; title: string; set_id: string | null; draft_id: string; status: 'queued' | 'running' | 'completed' | 'failed'; progress: string; error: string; unread: boolean; created_at: number; updated_at: number }
export type ValidationDetail = ValidationJob & { snapshot: ValidationSnapshot; documents: ReferenceDocument[]; result: { covered: boolean; proposals: Proposal[]; checked_pages: number; checked_cards: number } | null }
type Editor = { key: string; cards: CardInput[]; accept: (cards: CardInput[]) => void }
type Decisions = Record<number, 'accepted' | 'rejected'>
type Context = { jobs: ValidationJob[]; selected: ValidationDetail | null; start: (snapshot: ValidationSnapshot) => Promise<void>; review: (id: string) => void; register: (editor: Editor | null) => void; link: (draftId: string, setId: string) => Promise<void> }
const ValidationContext = createContext<Context | null>(null)
export const useValidationJobs = () => useContext(ValidationContext)!

async function read<T>(path: string, body?: unknown): Promise<T> {
  const response = await apiFetch(path, body === undefined ? {} : { method: 'POST', body: JSON.stringify(body) })
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Impossible de retrouver la validation. Réessaie.')
  return data as T
}

export function ValidationProvider({ children }: { children: ReactNode }) {
  const account = useAccount()
  const [jobs, setJobs] = useState<ValidationJob[]>([])
  const [selected, setSelected] = useState<ValidationDetail | null>(null)
  const [editor, setEditor] = useState<Editor | null>(null)
  const [notice, setNotice] = useState<ValidationJob | null>(null)
  const [error, setError] = useState('')
  const [decisions, setDecisions] = useState<Record<string, Decisions>>({})
  const notified = useRef(new Set<string>())
  const opening = useRef(0)
  const register = useCallback((value: Editor | null) => setEditor(value), [])
  const refresh = useCallback(async () => {
    const data = await read<{ jobs: ValidationJob[] }>('validation-jobs')
    setJobs(data.jobs)
    for (const job of data.jobs) {
      if (job.unread && (job.status === 'completed' || job.status === 'failed') && !notified.current.has(job.id)) {
        notified.current.add(job.id); setNotice(job)
      }
    }
    setSelected(current => {
      const job = current && data.jobs.find(item => item.id === current.id)
      return current && job ? { ...current, ...job } : current
    })
  }, [])
  useEffect(() => {
    if (!account) return
    let stopped = false
    let timer: number
    const poll = async () => {
      try { await refresh() } catch { /* A transient disconnect does not stop the server job. */ }
      if (!stopped) timer = window.setTimeout(() => { void poll() }, 4000)
    }
    void poll()
    const visible = () => { if (document.visibilityState === 'visible') void refresh().catch(() => {}) }
    document.addEventListener('visibilitychange', visible)
    return () => { stopped = true; window.clearTimeout(timer); document.removeEventListener('visibilitychange', visible) }
  }, [account?.user.username, refresh])
  const review = useCallback(async (id: string) => {
    const attempt = ++opening.current
    try {
      const job = await read<ValidationDetail>(`validation-jobs/${id}`)
      if (attempt !== opening.current) return
      setSelected(job); setError(''); setNotice(null)
      if (job.status === 'completed' || job.status === 'failed') {
        await read(`validation-jobs/${id}/read`, {})
        setJobs(current => current.map(item => item.id === id ? { ...item, unread: false } : item))
      }
    } catch (caught) { setError((caught as Error).message) }
  }, [])
  useEffect(() => {
    if (selected?.status === 'completed' && !selected.result) void review(selected.id)
  }, [selected?.id, selected?.status, selected?.result, review])
  const start = useCallback(async (snapshot: ValidationSnapshot) => {
    const job = await read<ValidationJob>('validation-jobs', snapshot)
    setJobs(current => [job, ...current.filter(item => item.id !== job.id)])
    setNotice(job); setSelected(null)
  }, [])
  const link = useCallback(async (draftId: string, setId: string) => {
    const data = await read<{ jobs: ValidationJob[] }>('validation-jobs/link', { draft_id: draftId, set_id: setId })
    setJobs(data.jobs)
    setSelected(current => current && current.draft_id === draftId ? { ...current, set_id: setId } : current)
  }, [])
  const compatible = !!selected && editor?.key === (selected.set_id || selected.draft_id)
  const openTarget = () => {
    if (selected) { window.dispatchEvent(new CustomEvent('memo:open-validation', { detail: selected })); setSelected(null) }
  }
  return <ValidationContext.Provider value={{ jobs, selected, start, review: id => { void review(id) }, register, link }}>
    {children}
    {notice && <div className="validation-toast" role="status" aria-live="polite">
      {notice.status === 'queued' || notice.status === 'running' ? <LoaderCircle className="import-spinner" size={20} /> : <Bell size={20} />}
      <div><strong>{notice.status === 'completed' ? 'Validation terminée' : notice.status === 'failed' ? 'La validation demande ton attention' : 'Validation lancée en arrière-plan'}</strong><span>{notice.title}</span></div>
      <button className="secondary-button" type="button" onClick={() => { void review(notice.id) }}>{notice.status === 'completed' ? 'Voir les résultats' : 'Voir'}</button>
      <button className="icon-button" type="button" aria-label="Fermer la notification de validation" onClick={() => setNotice(null)}><X size={16} /></button>
    </div>}
    {error && <div className="validation-toast" role="alert"><span>{error}</span><button className="icon-button" aria-label="Fermer l’erreur de validation" onClick={() => setError('')}><X size={16} /></button></div>}
    {selected && <CardValidationDialog key={selected.id} job={selected} currentCards={compatible ? editor!.cards : null}
      decisions={Object.fromEntries(Object.entries(decisions[selected.id] || {}).filter(([index, decision]) => decision !== 'accepted' || !compatible || editor!.cards.some(card => card.term === selected.result?.proposals[Number(index)]?.term && card.definition === selected.result?.proposals[Number(index)]?.definition)))} onDecisions={value => setDecisions(current => ({ ...current, [selected.id]: value }))}
      onClose={() => { ++opening.current; setSelected(null) }} onOpenTarget={openTarget}
      onRetry={() => { void start(selected.snapshot).catch(caught => setError((caught as Error).message)) }}
      onAccept={cards => { if (compatible) editor!.accept(cards) }} />}
  </ValidationContext.Provider>
}

export function ValidationSidebar() {
  const { jobs, review } = useValidationJobs()
  if (!jobs.length) return null
  const visible = jobs.filter(job => job.status === 'running' || job.status === 'queued' || job.unread)
  for (const job of jobs) if (visible.length < 4 && !visible.some(item => item.id === job.id)) visible.push(job)
  return <section className="validation-sidebar" aria-label="Validations des cartes"><span className="validation-sidebar-label">VALIDATIONS</span>
    {visible.slice(0, 4).map(job => <button type="button" key={job.id} className="validation-job" onClick={() => review(job.id)}>
      {job.status === 'running' || job.status === 'queued' ? <LoaderCircle size={18} className="import-spinner" /> : job.unread ? <Bell size={18} /> : <CheckCircle2 size={18} />}
      <span><strong>{job.title}</strong><small>{job.status === 'completed' ? 'Résultats disponibles' : job.status === 'failed' ? 'À relancer' : job.progress}</small></span>
      {job.unread && <i aria-label="Nouvelle notification" />}
    </button>)}
  </section>
}
