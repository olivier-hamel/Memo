import { Check, CheckCircle2, LoaderCircle, Plus, X } from 'lucide-react'
import Dialog from './Dialog'
import type { CardInput } from './types'
import type { ValidationDetail } from './ValidationJobs'

type Decisions = Record<number, 'accepted' | 'rejected'>
export default function CardValidationDialog({ job, currentCards, decisions, onDecisions, onAccept, onClose, onOpenTarget, onRetry }: {
  job: ValidationDetail; currentCards: CardInput[] | null; decisions: Decisions; onDecisions: (value: Decisions) => void
  onAccept: (cards: CardInput[]) => void; onClose: () => void; onOpenTarget: () => void; onRetry: () => void
}) {
  const result = job.result
  const complete = result && typeof result.covered === 'boolean' && Array.isArray(result.proposals)
    && result.covered === (result.proposals.length === 0) && result.checked_cards === job.snapshot.cards.length
    && result.checked_pages === job.documents.reduce((sum, document) => sum + document.page_count, 0)
  const error = job.error || (job.status === 'completed' && result && !complete ? 'Tous les documents et toutes les cartes n’ont pas été vérifiés. Réessaie.' : '')
  const acceptedCount = Object.values(decisions).filter(value => value === 'accepted').length
  const capacity = 300 - (currentCards?.length || 0)
  const decide = (indices: number[], accept: boolean) => {
    if (!result || (accept && !currentCards)) return
    const pending = indices.filter(index => !decisions[index])
    const existing = new Set(currentCards?.map(card => JSON.stringify([card.term.trim(), card.definition.trim()])))
    const additions = pending.map(index => result.proposals[index]).filter(card => {
      const key = JSON.stringify([card.term.trim(), card.definition.trim()])
      if (existing.has(key)) return false
      existing.add(key); return true
    })
    if (accept && additions.length > capacity) return
    const next = { ...decisions }
    for (const index of pending) next[index] = accept ? 'accepted' : 'rejected'
    if (accept && additions.length) onAccept(additions.map(({ term, definition }) => ({ term, definition })))
    onDecisions(next)
  }
  const remaining = result?.proposals.map((_, index) => index).filter(index => !decisions[index]) || []
  return <Dialog title="Validation des cartes" onClose={onClose}><div className="card-validation">
    {job.status === 'completed' && !result && !error && <div className="validation-status" role="status"><LoaderCircle size={28} className="import-spinner" /><p>Chargement des résultats…</p></div>}
    {(job.status === 'queued' || job.status === 'running') && <><div className="validation-status" role="status"><LoaderCircle size={28} className="import-spinner" /><p>{job.progress}</p><small>Tu peux fermer cette fenêtre et continuer à utiliser mémo. Une notification t’avertira quand le résultat sera prêt.</small></div><div className="modal-actions"><button type="button" className="primary-button" onClick={onClose}>Continuer en arrière-plan</button></div></>}
    {error && <><p className="detail-error" role="alert">{error}</p><div className="modal-actions"><button className="secondary-button" type="button" onClick={onClose}>Fermer</button><button className="primary-button" type="button" onClick={onRetry}>Réessayer</button></div></>}
    {complete && !error && result!.covered && <><div className="validation-status" role="status"><CheckCircle2 size={34} /><h3>Aucun manque détecté</h3><p>La comparaison des cartes envoyées avec tous les documents n’a pas repéré d’information supplémentaire à ajouter.</p></div><div className="modal-actions"><button className="primary-button" type="button" onClick={onClose}>Terminer<Check size={16} /></button></div></>}
    {complete && !error && !result!.covered && <>
      <p className="modal-description">mémo propose {result!.proposals.length} carte{result!.proposals.length > 1 ? 's' : ''} pour compléter les informations manquantes. Accepte ou refuse chaque proposition.</p>
      <p className="validation-snapshot-note">Comparaison basée sur les cartes et documents envoyés au lancement de la validation.</p>
      {!currentCards && <div className="validation-open-target"><p>Ouvre l’ensemble pour ajouter les propositions à tes cartes.</p><button className="secondary-button" type="button" onClick={onOpenTarget}>{job.set_id ? 'Ouvrir l’ensemble' : 'Retrouver le brouillon'}</button></div>}
      {acceptedCount > 0 && <p className="validation-added" role="status">{acceptedCount} carte{acceptedCount > 1 ? 's acceptées' : ' acceptée'}. Enregistre tes modifications pour les conserver.</p>}
      {currentCards && capacity === 0 && remaining.length > 0 && <p className="detail-error" role="status">La limite de 300 cartes est atteinte. Libère de la place dans ton ensemble pour ajouter d’autres cartes.</p>}
      <ol className="validation-proposals">{result!.proposals.map((proposal, index) => <li key={index} className={decisions[index] ? `is-${decisions[index]}` : ''}>
        <h3>{proposal.term}</h3><p className="validation-definition">{proposal.definition}</p>
        <small className="validation-source">{job.documents.find(document => document.id === proposal.document_id)?.name} · page {proposal.page}</small>
        {decisions[index] ? <p className="validation-decision">{decisions[index] === 'accepted' ? <Check size={15} /> : <X size={15} />}{decisions[index] === 'accepted' ? 'Acceptée' : 'Refusée'}</p> : <div className="validation-card-actions"><button className="secondary-button" type="button" onClick={() => decide([index], false)}>Refuser</button><button className="primary-button" type="button" disabled={!currentCards || capacity <= 0} onClick={() => decide([index], true)}><Plus size={15} />Accepter</button></div>}
      </li>)}</ol>
      <div className="modal-actions validation-actions">{remaining.length > 0 && <><button className="secondary-button" type="button" onClick={() => decide(remaining, false)}>Tout refuser</button><button className="secondary-button" type="button" disabled={!currentCards || remaining.length > capacity} onClick={() => decide(remaining, true)}>Tout accepter</button></>}<button className="primary-button" type="button" onClick={onClose}>Terminer</button></div>
    </>}
  </div></Dialog>
}
