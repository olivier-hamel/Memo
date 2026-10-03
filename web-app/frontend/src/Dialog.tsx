import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { X } from 'lucide-react'

export default function Dialog({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const close = useRef(onClose)
  close.current = onClose
  useEffect(() => {
    const node = dialog.current!
    node.showModal()
    const cancel = (event: Event) => { event.preventDefault(); close.current() }
    node.addEventListener('cancel', cancel)
    return () => { node.removeEventListener('cancel', cancel); node.close() }
  }, [])
  return <dialog ref={dialog} className="modal" aria-label={title} onClick={event => {
    if (event.target === dialog.current) {
      const rect = dialog.current.getBoundingClientRect()
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) close.current()
    }
  }}>
    <div className="modal-heading"><h2>{title}</h2><button className="icon-button" aria-label="Fermer" onClick={onClose}><X size={20} /></button></div>
    {children}
  </dialog>
}
