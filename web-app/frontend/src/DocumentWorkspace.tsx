import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties, PointerEvent, ReactNode } from 'react'
import { Check, ChevronDown, Files, FileText, GripVertical, LoaderCircle, PanelRightClose, PanelRightOpen, Plus, Trash2, Undo2, X } from 'lucide-react'
import { apiFetch } from './api'
import { useAccount } from './AuthGate'
import type { ReferenceDocument } from './types'
import { clamp, stored, remember } from './readerStorage'
import Dialog from './Dialog'
import './documents.css'

const DocumentReader = lazy(() => import('./DocumentReader'))
const MAX_DOCUMENTS = 20

export default function DocumentWorkspace({ children, header, documents, onDocuments, editable, disabled, setId, onUploading }: {
  children: ReactNode; header: ReactNode; documents: ReferenceDocument[]; onDocuments: (documents: ReferenceDocument[]) => void
  editable: boolean; disabled: boolean; setId?: string; onUploading: (uploading: boolean) => void
}) {
  const account = useAccount()
  const storagePrefix = `memo:reader:${account?.user.username || 'local'}`
  const [open, setOpen] = useState(() => stored(storagePrefix + ':open', false))
  const [selected, setSelected] = useState(() => stored(storagePrefix + ':selected', '') || documents[0]?.id || '')
  const [ratio, setRatio] = useState(() => clamp(Number(stored(storagePrefix + ':width', 50)) || 50, 30, 70))
  const [mobilePanel, setMobilePanel] = useState<'cards' | 'document'>('cards')
  const [uploading, setUploading] = useState(false)
  const [uploadName, setUploadName] = useState('')
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [removedDocument, setRemovedDocument] = useState<{ document: ReferenceDocument; index: number; wasActive: boolean } | null>(null)
  const workspace = useRef<HTMLDivElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const uploadPending = useRef(false)
  const uploadAbort = useRef<AbortController | null>(null)
  const [controlsTarget, setControlsTarget] = useState<HTMLDivElement | null>(null)
  const attachControls = useCallback((element: HTMLDivElement | null) => setControlsTarget(element), [])
  const active = documents.find(document => document.id === selected) || documents[0]
  useEffect(() => () => uploadAbort.current?.abort(), [])
  useEffect(() => { remember(storagePrefix + ':width', ratio) }, [storagePrefix, ratio])
  useEffect(() => { remember(storagePrefix + ':open', open) }, [storagePrefix, open])
  useEffect(() => { if (active) remember(storagePrefix + ':selected', active.id) }, [storagePrefix, active])
  const upload = async (files: File[]) => {
    if (uploadPending.current || !files.length) return
    if (documents.length + files.length > MAX_DOCUMENTS) { setError('Tu peux ajouter au maximum 20 documents par ensemble.'); return }
    if (files.some(file => !/\.(pdf|ppt|pptx)$/i.test(file.name) || !file.size || file.size > 30 * 1024 * 1024)) {
      setError('Choisis des fichiers PDF, PPT ou PPTX non vides de 30 Mio maximum chacun.'); return
    }
    uploadPending.current = true
    setUploading(true); onUploading(true); setError('')
    const added = [...documents]
    const failures: string[] = []
    const abort = new AbortController()
    uploadAbort.current = abort
    try {
      for (const file of files) {
        setUploadName(file.name)
        try {
          const response = await apiFetch('reference-documents', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-Memo-Filename': encodeURIComponent(file.name) }, body: file, signal: abort.signal })
          const result = await response.json()
          if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'L’ajout du document a échoué.')
          if (abort.signal.aborted) break
          added.push(result as ReferenceDocument)
          onDocuments([...added]); setSelected(result.id); setOpen(true)
        } catch (caught) {
          if (abort.signal.aborted) break
          failures.push(`${file.name} : ${(caught as Error).message}`)
        }
      }
      if (!abort.signal.aborted) setError(failures.join('\n'))
    } finally {
      uploadPending.current = false
      if (!abort.signal.aborted) { setUploading(false); onUploading(false); setUploadName('') }
    }
  }
  const resize = (event: PointerEvent<HTMLDivElement>) => {
    const bounds = workspace.current!.getBoundingClientRect()
    setRatio(clamp((event.clientX - bounds.left) / bounds.width * 100, 30, 70))
  }
  const removeDocument = (document: ReferenceDocument) => {
    if (!editable || disabled || uploadPending.current) return
    const remaining = documents.filter(item => item.id !== document.id)
    setRemovedDocument({ document, index: documents.indexOf(document), wasActive: active?.id === document.id })
    onDocuments(remaining)
    if (active?.id === document.id) setSelected(remaining[0]?.id || '')
    if (!remaining.length) setOpen(false)
  }
  const restoreDocument = () => {
    if (!removedDocument || disabled || uploading || documents.length >= MAX_DOCUMENTS) return
    const restored = [...documents]
    restored.splice(Math.min(removedDocument.index, restored.length), 0, removedDocument.document)
    onDocuments(restored)
    if (removedDocument.wasActive) { setSelected(removedDocument.document.id); setOpen(true) }
    setRemovedDocument(null)
  }
  const management = <div className="reference-management">
    {editable && <input ref={fileInput} className="sr-only" type="file" multiple accept=".pdf,.ppt,.pptx" aria-label="Ajouter des documents de référence" disabled={disabled || uploading} onChange={event => { void upload(Array.from(event.target.files || [])); event.target.value = '' }} />}
    {(!open || !active) && <div className="reference-toolbar">
      <div className="reference-toolbar-title"><FileText size={18} /><div><strong>Documents de référence</strong><span>Ton cours à côté de tes cartes</span></div>{documents.length > 0 && <small>{documents.length}</small>}</div>
      <div className="reference-toolbar-actions">
        {editable && <button type="button" className="secondary-button" disabled={disabled || uploading || documents.length >= MAX_DOCUMENTS} onClick={() => fileInput.current?.click()}>{uploading ? <LoaderCircle size={16} className="import-spinner" /> : <Plus size={16} />}{uploading ? 'Ajout en cours…' : 'Ajouter des documents'}</button>}
        {(!open || !active) && <button type="button" className="secondary-button" aria-haspopup="dialog" aria-expanded={pickerOpen} onClick={() => setPickerOpen(true)}><Files size={16} />Choisir un document</button>}
        <button type="button" className={`secondary-button ${open ? 'reader-toggle-active' : ''}`} aria-expanded={open} aria-controls="reference-reader" onClick={() => setOpen(current => !current)}>{open ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}{open ? 'Masquer le lecteur' : 'Afficher le lecteur'}</button>
      </div>
    </div>}
    {uploading && <p className="reference-upload-status" role="status">{uploadName} · Ajout et conversion du document… Tu peux continuer à écrire tes cartes.</p>}
    {error && <p className="detail-error reference-upload-error" role="alert">{error}</p>}
    {open && active && <div className="reference-document-choice">
      <div className="reference-choice-heading"><FileText size={16} /><strong>Document à consulter</strong><span>{documents.length} document{documents.length > 1 ? 's' : ''}</span></div>
      <div className="reference-document-picker"><button type="button" className="reference-choose" aria-label="Choisir un document" aria-haspopup="dialog" aria-expanded={pickerOpen} onClick={() => setPickerOpen(true)}><span><span className="reference-choose-name"><strong>{active.name}</strong><ChevronDown size={14} aria-hidden="true" /></span><small>Choisir un document</small></span></button>
        <button className="reference-close" type="button" aria-label="Fermer le lecteur de documents" title="Fermer le lecteur de documents" onClick={() => setOpen(false)}><X size={20} /></button>
      </div>
    </div>}
    <div className="reference-reader-tools" ref={attachControls} />
  </div>
  return <section className={`document-workspace ${open ? 'reader-is-open' : ''}`} aria-label="Cartes et documents de référence">
    <div ref={workspace} className={`reference-split ${open ? 'is-open' : ''} ${dragging ? 'is-dragging' : ''} mobile-${mobilePanel}`} style={{ '--editor-width': `${ratio}%` } as CSSProperties}>
      <div className="reference-editor" id="reference-editor">
        <div className="reference-editor-header">{header}</div>
        {!open && management}
    {open && <div className="reference-mobile-tabs" aria-label="Panneau affiché"><button type="button" aria-pressed={mobilePanel === 'cards'} onClick={() => setMobilePanel('cards')}>Cartes</button><button type="button" aria-pressed={mobilePanel === 'document'} onClick={() => setMobilePanel('document')}>Document</button></div>}
        <div className="reference-card-content">{children}</div>
      </div>
      {open && <>
        <div className="reference-divider" role="separator" tabIndex={0} aria-label="Largeur du panneau de cartes" aria-orientation="vertical" aria-valuemin={30} aria-valuemax={70} aria-valuenow={Math.round(ratio)} aria-controls="reference-editor reference-reader"
          onPointerDown={event => { event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); setDragging(true); resize(event) }}
          onPointerMove={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) resize(event) }}
          onPointerUp={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); setDragging(false) }}
          onLostPointerCapture={() => setDragging(false)} onPointerCancel={() => setDragging(false)} onDoubleClick={() => setRatio(50)}
          onKeyDown={event => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); setRatio(current => event.key === 'Home' ? 30 : event.key === 'End' ? 70 : clamp(current + (event.key === 'ArrowLeft' ? -2 : 2), 30, 70)) } }}><GripVertical size={18} /></div>
        <aside className="reference-reader" id="reference-reader" aria-label="Lecteur de documents">
          {management}
          {active ? <Suspense fallback={<div className="reference-empty" role="status"><LoaderCircle size={26} className="import-spinner" /><p>Ouverture du lecteur…</p></div>}><DocumentReader key={active.id} document={active} setId={setId} storagePrefix={storagePrefix} controlsTarget={controlsTarget} /></Suspense> : <div className="reference-empty"><FileText size={35} /><h3>Ton cours, à portée de main</h3><p>Ajoute un PDF ou un PowerPoint pour le consulter pendant la création de tes cartes. Les notes et commentaires s’affichent dans le lecteur, sous chaque diapositive.</p><small>PDF, PPT, PPTX · 30 Mio par fichier · 20 documents</small>{editable && <button type="button" className="secondary-button" disabled={disabled || uploading} onClick={() => fileInput.current?.click()}><Plus size={16} />Ajouter un document</button>}</div>}
        </aside>
      </>}
    </div>
    {pickerOpen && <Dialog title="Choisir un document" onClose={() => setPickerOpen(false)}>
      <p className="modal-description">Retrouve tous les documents de cet ensemble. Choisis celui que tu veux consulter à côté de tes cartes.</p>
      {documents.length ? <ul className="reference-document-list" aria-label="Documents disponibles">{documents.map(document => <li key={document.id} className={`reference-document-item ${open && active?.id === document.id ? 'is-current' : ''}`}>
        <button type="button" className="reference-document-open" aria-label={`Consulter ${document.name}`} onClick={() => { setSelected(document.id); setOpen(true); setMobilePanel('document'); setPickerOpen(false) }}>
          <span className="reference-file-icon"><FileText size={22} /></span><span className="reference-document-info"><strong>{document.name}</strong><small>{document.kind.toUpperCase()} · {document.page_count} {document.kind === 'pdf' ? 'page' : 'slide'}{document.page_count > 1 ? 's' : ''}</small></span>
          {open && active?.id === document.id && <span className="reference-current"><Check size={16} /><span>En cours</span></span>}
        </button>
        {editable && <button type="button" className="reference-delete" aria-label={`Supprimer ${document.name}`} title="Retirer ce document de l’ensemble" disabled={disabled || uploading} onClick={() => removeDocument(document)}><Trash2 size={18} /></button>}
      </li>)}</ul> : <div className="reference-picker-empty"><Files size={32} /><p>Aucun document pour le moment.</p></div>}
      {removedDocument && <div className="reference-removal-notice" role="status"><span>{removedDocument.document.name} retiré de l’ensemble.</span><button type="button" disabled={disabled || uploading || documents.length >= MAX_DOCUMENTS} onClick={restoreDocument}><Undo2 size={15} />Annuler</button></div>}
      <div className="reference-picker-footer">
        {editable && <button type="button" className="secondary-button" disabled={disabled || uploading || documents.length >= MAX_DOCUMENTS} onClick={() => { setPickerOpen(false); fileInput.current?.click() }}><Plus size={16} />Ajouter des documents</button>}
        <button type="button" className="secondary-button" onClick={() => setPickerOpen(false)}>Fermer la fenêtre</button>
      </div>
      {editable && <p className="modal-footnote">Enregistre l’ensemble pour conserver les ajouts et les suppressions.</p>}
    </Dialog>}
  </section>
}
