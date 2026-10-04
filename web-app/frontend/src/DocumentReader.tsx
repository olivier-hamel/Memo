import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { BookOpen, ChevronLeft, ChevronRight, FileText, LoaderCircle, MessageSquare, ZoomIn, ZoomOut } from 'lucide-react'
import { getDocument, GlobalWorkerOptions, TextLayer } from 'pdfjs-dist'
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { memoBase } from './api'
import { readLibrary } from './libraryApi'
import type { ReferenceDocument, SlideComment } from './types'
import { clamp, stored, remember } from './readerStorage'

GlobalWorkerOptions.workerSrc = workerUrl

function PdfPage({ pdf, number, width, zoom, scroll, initialRatio }: {
  pdf: PDFDocumentProxy; number: number; width: number; zoom: number; scroll: HTMLDivElement | null; initialRatio: number
}) {
  const element = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const text = useRef<HTMLDivElement>(null)
  const [near, setNear] = useState(false)
  const [ratio, setRatio] = useState(initialRatio)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!scroll) return
    const observer = new IntersectionObserver(entries => setNear(entries[0].isIntersecting), { root: scroll, rootMargin: '700px 0px' })
    observer.observe(element.current!)
    return () => observer.disconnect()
  }, [scroll])
  useEffect(() => {
    if (!near || width <= 0) return
    let cancelled = false
    let rendering: RenderTask | undefined
    let layer: TextLayer | undefined
    const surface = canvas.current!
    const textContainer = text.current!
    setError('')
    void (async () => {
      const page = await pdf.getPage(number)
      if (cancelled) return
      const base = page.getViewport({ scale: 1 })
      setRatio(base.width / base.height)
      const scale = width * zoom / base.width
      const viewport = page.getViewport({ scale })
      // Bound canvas memory even on high-DPI displays and at 200% zoom.
      const density = Math.min(window.devicePixelRatio || 1, 2, Math.sqrt(8_000_000 / (viewport.width * viewport.height)))
      surface.width = Math.max(1, Math.floor(viewport.width * density))
      surface.height = Math.max(1, Math.floor(viewport.height * density))
      textContainer.replaceChildren()
      textContainer.style.setProperty('--total-scale-factor', String(scale))
      textContainer.style.setProperty('--scale-round-x', '1px')
      textContainer.style.setProperty('--scale-round-y', '1px')
      rendering = page.render({ canvas: surface, viewport, transform: density === 1 ? undefined : [density, 0, 0, density, 0, 0] })
      await rendering.promise
      if (cancelled) return
      layer = new TextLayer({ textContentSource: page.streamTextContent(), container: textContainer, viewport })
      await layer.render()
    })().catch(caught => {
      if (!cancelled && caught?.name !== 'RenderingCancelledException' && caught?.name !== 'AbortException') setError('Cette page n’a pas pu être affichée.')
    })
    return () => {
      cancelled = true
      rendering?.cancel(); layer?.cancel()
      // Free offscreen canvases rather than retaining hundreds of rendered pages.
      surface.width = 0; surface.height = 0
      textContainer.replaceChildren()
    }
  }, [pdf, number, width, zoom, near])
  return <div className="reference-page" ref={element} data-page={number} style={{ width: width * zoom, aspectRatio: ratio }} aria-label={`Page ${number}`}>
    <canvas ref={canvas} aria-hidden="true" />
    <div className="textLayer" ref={text} />
    {error && <p className="page-render-error" role="alert">{error}</p>}
    <span className="reference-page-number" aria-hidden="true">{number}</span>
  </div>
}

export default function DocumentReader({ document, setId, storagePrefix, controlsTarget }: { document: ReferenceDocument; setId?: string; storagePrefix: string; controlsTarget: HTMLDivElement | null }) {
  const positionKey = `${storagePrefix}:document:${document.id}`
  const saved = stored<{ page: number; zoom: number }>(positionKey, { page: 1, zoom: 1 })
  const [page, setPage] = useState(() => clamp(saved.page || 1, 1, document.page_count))
  const [zoom, setZoom] = useState(() => clamp(saved.zoom || 1, .5, 2))
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null)
  const [notes, setNotes] = useState<string[]>([])
  const [comments, setComments] = useState<SlideComment[][]>([])
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [width, setWidth] = useState(0)
  const [initialRatio, setInitialRatio] = useState(4 / 3)
  const [scroll, setScroll] = useState<HTMLDivElement | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const attachScroll = useCallback((element: HTMLDivElement | null) => { scrollRef.current = element; setScroll(element) }, [])
  const restoring = useRef(true)
  const positionedPage = useRef<{ page: number; top: number } | null>(null)
  const currentPage = useRef(page)
  currentPage.current = page
  const powerpoint = document.kind !== 'pdf'
  const label = powerpoint ? 'Slide' : 'Page'
  const suffix = setId ? `?set_id=${encodeURIComponent(setId)}` : ''
  useEffect(() => { remember(positionKey, { page, zoom }) }, [positionKey, page, zoom])
  useEffect(() => {
    let cancelled = false
    setPdf(null); setError(''); setNotes([]); setComments([]); restoring.current = true
    const task = getDocument({ url: `${memoBase}api/reference-documents/${document.id}/pdf${suffix}`, withCredentials: true,
      cMapUrl: `${memoBase}pdf-assets/cmaps/`, cMapPacked: true, standardFontDataUrl: `${memoBase}pdf-assets/standard_fonts/`,
      wasmUrl: `${memoBase}pdf-assets/wasm/` })
    void Promise.all([task.promise, readLibrary<ReferenceDocument & { notes: string[]; comments?: SlideComment[][] }>(`reference-documents/${document.id}${suffix}`)]).then(async ([loaded, metadata]) => {
      const first = await loaded.getPage(1)
      if (cancelled) return
      const viewport = first.getViewport({ scale: 1 })
      setInitialRatio(viewport.width / viewport.height)
      setNotes(metadata.notes); setComments(metadata.comments || []); setPdf(loaded)
    }).catch(() => { if (!cancelled) setError('Le document n’a pas pu être chargé. Vérifie ta connexion, puis réessaie.') })
    return () => { cancelled = true; void task.destroy().catch(() => {}) }
  }, [document.id, suffix, retry])
  useEffect(() => {
    if (!scroll) return
    const observer = new ResizeObserver(() => {
      const next = Math.max(0, scroll.clientWidth)
      if (next > 0) setWidth(next)
    })
    observer.observe(scroll)
    return () => observer.disconnect()
  }, [scroll])
  useEffect(() => {
    if (!pdf || !scroll || width <= 0) return
    const target = scroll.querySelector<HTMLElement>(`[data-slide="${currentPage.current}"]`)
    if (target) {
      scroll.scrollTop = target.offsetTop
      positionedPage.current = { page: currentPage.current, top: scroll.scrollTop }
    }
    // Restore page after document/zoom/width changes without resetting the editor.
    restoring.current = false
  }, [pdf, scroll, width, zoom])
  const navigate = (next: number) => {
    const value = clamp(next, 1, document.page_count)
    setPage(value)
    const target = scrollRef.current?.querySelector<HTMLElement>(`[data-slide="${value}"]`)
    if (target) {
      const container = scrollRef.current!
      container.scrollTop = target.offsetTop
      positionedPage.current = { page: value, top: container.scrollTop }
    }
  }
  const onScroll = () => {
    const container = scrollRef.current
    if (!container || !container.clientWidth || !container.clientHeight || restoring.current) return
    // A short last slide cannot always align with the top of the viewport.
    // Keep explicit navigation authoritative until the user actually scrolls.
    if (positionedPage.current && Math.abs(container.scrollTop - positionedPage.current.top) < 1) {
      setPage(positionedPage.current.page)
      return
    }
    positionedPage.current = null
    const candidates = [...container.querySelectorAll<HTMLElement>('[data-slide]')]
    if (container.scrollTop > 0 && container.scrollTop + container.clientHeight >= container.scrollHeight - 2) {
      setPage(document.page_count); return
    }
    const top = container.scrollTop + Math.min(container.clientHeight * .25, 150)
    const active = candidates.find(element => element.offsetTop + element.offsetHeight > top)
    if (active) setPage(Number(active.dataset.slide))
  }
  return <>
    {controlsTarget && createPortal(<>
    <div className="reference-controls" aria-label="Navigation du document">
      <div className="reference-pagination">
        <button type="button" className="icon-button" aria-label={`${label} précédente`} disabled={!pdf || page <= 1} onClick={() => navigate(page - 1)}><ChevronLeft size={18} /></button>
        <label>{label} <input type="number" min={1} max={document.page_count} aria-label={`Numéro de ${label.toLowerCase()}`} value={page} disabled={!pdf} onChange={event => { if (event.target.value) navigate(Number(event.target.value)) }} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); event.currentTarget.blur() } }} /></label><span>/ {document.page_count}</span>
        <button type="button" className="icon-button" aria-label={`${label} suivante`} disabled={!pdf || page >= document.page_count} onClick={() => navigate(page + 1)}><ChevronRight size={18} /></button>
      </div>
      <div className="reference-zoom">
        <button type="button" className="icon-button" aria-label="Dézoomer" disabled={!pdf || zoom <= .5} onClick={() => setZoom(current => clamp(current - .1, .5, 2))}><ZoomOut size={17} /></button>
        <button type="button" className="reference-fit" title="Ajuster à la largeur" disabled={!pdf} onClick={() => setZoom(1)}>{Math.round(zoom * 100)} %</button>
        <button type="button" className="icon-button" aria-label="Zoomer" disabled={!pdf || zoom >= 2} onClick={() => setZoom(current => clamp(current + .1, .5, 2))}><ZoomIn size={17} /></button>
      </div>
    </div>
    </>, controlsTarget)}
    {error ? <div className="reference-empty" role="alert"><FileText size={30} /><p>{error}</p><button type="button" className="secondary-button" onClick={() => setRetry(value => value + 1)}>Réessayer</button></div> : !pdf ? <div className="reference-empty" role="status"><LoaderCircle size={26} className="import-spinner" /><p>Ouverture du document…</p></div> : null}
    <div className="reference-scroll" ref={attachScroll} onScroll={onScroll} tabIndex={0} aria-label={`Pages de ${document.name}`} style={{ display: pdf ? undefined : 'none' }}>
      {pdf && Array.from({ length: document.page_count }, (_, index) => <div className="reference-slide" key={index + 1} data-slide={index + 1} style={{ width: width * zoom }}>
        <PdfPage pdf={pdf} number={index + 1} width={width} zoom={zoom} scroll={scroll} initialRatio={initialRatio} />
        {powerpoint && (notes[index] || comments[index]?.length) ? <div className="reference-annotations" style={{ maxWidth: width }}>
          {notes[index] && <section className="presenter-notes" aria-label={`Notes du présentateur — Slide ${index + 1}`}>
            <h3><BookOpen size={17} />Notes du présentateur <span>Slide {index + 1}</span></h3>
            <div>{notes[index]}</div>
          </section>}
          {!!comments[index]?.length && <section className="presenter-notes slide-comments" aria-label={`Commentaires — Slide ${index + 1}`}>
            <h3><MessageSquare size={17} />Commentaires <span>Slide {index + 1}</span></h3>
            <div>{comments[index].map((comment, commentIndex) => <article key={commentIndex} className="slide-comment">
              <strong>{comment.author || 'Commentaire'}</strong><p>{comment.text}</p>
              {comment.replies.map((reply, replyIndex) => <div key={replyIndex} className="slide-comment-reply"><strong>{reply.author ? `Réponse de ${reply.author}` : 'Réponse'}</strong><p>{reply.text}</p></div>)}
            </article>)}</div>
          </section>}
        </div> : null}
      </div>)}
    </div>
  </>
}
