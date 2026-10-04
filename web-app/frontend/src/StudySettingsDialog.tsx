import { useState } from 'react'
import { RotateCcw } from 'lucide-react'
import Dialog from './Dialog'
import type { StudyConfig } from './types'

type NumericKey = { [K in keyof StudyConfig]: StudyConfig[K] extends number ? K : never }[keyof StudyConfig]
type Field = { key: NumericKey; label: string; help: string; min?: number; max?: number; step?: number | 'any'; percent?: boolean }

const mastery: Field[] = [
  { key: 'familiar_after', label: 'Réussites pour devenir familière', help: 'Nombre de bonnes réponses consécutives avant l’état « Familière ».' },
  { key: 'minimum_successful_recalls', label: 'Réussites pour devenir maîtrisée', help: 'Minimum de bonnes réponses consécutives. Les autres critères de maîtrise doivent aussi être remplis.', min: 2 },
  { key: 'mastery_threshold', label: 'Score minimum de maîtrise (%)', help: 'Score calculé à partir des réponses et de leur espacement ; ce n’est pas le pourcentage de bonnes réponses.', min: 1, max: 99, percent: true },
  { key: 'minimum_spaced_recalls', label: 'Réussites espacées pour la maîtrise', help: 'Minimum de bonnes réponses séparées par d’autres questions ou par le délai d’une carte seule.' },
  { key: 'minimum_active_recall_successes', label: 'Rappels actifs pour la maîtrise', help: 'Minimum de réussites espacées sans choix de réponse, par autoévaluation ou réponse écrite.' },
]
const spacing: Field[] = [
  { key: 'minimum_spacing_questions', label: 'Questions entre deux rappels', help: 'Nombre de questions intermédiaires pour compter une réussite comme espacée. Limité au nombre d’autres cartes du groupe.' },
  { key: 'minimum_spacing', label: 'Espacement pour une carte seule (secondes)', help: 'Délai minimum entre deux réponses quand un groupe ne contient qu’une carte.', step: 'any', min: 0.01 },
  { key: 'learning_interval', label: 'Délai en apprentissage (secondes)', help: 'Délai de prochaine révision pour une carte non maîtrisée ; sert aussi de minimum de stabilité après une erreur.', step: 0.01, min: 0.01 },
  { key: 'review_interval', label: 'Délai après maîtrise (secondes)', help: 'Délai minimum de prochaine révision pour une carte maîtrisée. Il ne débloque pas les groupes suivants.', step: 0.01, min: 0.01 },
]
const priorities: Field[] = [
  { key: 'weight_new', label: 'Priorité des cartes nouvelles', help: 'S’applique aussi aux cartes à confirmer lors de la maîtrise finale.', step: 0.01, min: 0.01 },
  { key: 'weight_learning', label: 'Priorité des cartes en apprentissage', help: 'Une valeur plus élevée augmente leur fréquence de sélection.', step: 0.01, min: 0.01 },
  { key: 'weight_familiar', label: 'Priorité des cartes familières', help: 'Pondération relative lors de la sélection de la prochaine carte.', step: 0.01, min: 0.01 },
  { key: 'weight_mastered', label: 'Priorité des cartes maîtrisées', help: 'Permet de renforcer les acquis tant que le groupe est actif.', step: 0.01, min: 0.01 },
  { key: 'incorrect_answer_penalty', label: 'Baisse du score après une erreur (%)', help: 'Part du score retirée après une erreur. Une erreur remet aussi les compteurs de réussites à zéro.', min: 1, max: 99, percent: true },
]

export default function StudySettingsDialog({ config, defaults, busy, error, onSave, onClose }: {
  config: StudyConfig; defaults: StudyConfig; busy: boolean; error: string
  onSave: (config: StudyConfig) => Promise<boolean>; onClose: () => void
}) {
  const [draft, setDraft] = useState(config)
  const [restored, setRestored] = useState(false)
  const update = <K extends keyof StudyConfig>(key: K, value: StudyConfig[K]) => {
    setDraft(previous => ({ ...previous, [key]: value }))
    setRestored(false)
  }
  const field = ({ key, label, help, min = 1, max, step = 1, percent }: Field) => <label className="study-setting-field" key={key}>
    <span>{label}</span>
    <input type="number" aria-label={label} required min={min} max={max} step={step} value={Number.isFinite(draft[key]) ? Number((draft[key] * (percent ? 100 : 1)).toFixed(8)) : ''}
      onChange={event => update(key, event.target.value === '' ? NaN : event.target.valueAsNumber / (percent ? 100 : 1))}
      aria-describedby={`setting-help-${key}`} />
    <small id={`setting-help-${key}`}>{help}</small>
  </label>
  const toggle = (key: 'allow_typed_recall' | 'allow_reverse_direction' | 'allow_multiple_choice', label: string, help: string) => <div className="setting-row" key={key}>
    <div><strong>{label}</strong><p id={`setting-help-${key}`}>{help}</p></div>
    <button type="button" className={`toggle ${draft[key] ? 'on' : ''}`} role="switch" aria-label={label}
      aria-describedby={`setting-help-${key}`} aria-checked={draft[key]} onClick={() => update(key, !draft[key])}><span /></button>
  </div>

  return <Dialog title="Configuration de l’apprentissage" onClose={onClose}>
    <form className="study-settings" onSubmit={async event => {
      event.preventDefault()
      if (await onSave(draft)) onClose()
    }}>
      <p className="modal-description">Ces réglages sont enregistrés pour cet ensemble et cette version. Les réponses sont conservées ; les nouveaux critères s’appliquent au groupe actif. Les groupes déjà terminés restent acquis.</p>
      <fieldset disabled={busy}>
        <section className="study-settings-section"><h3>Groupes et progression</h3>
          {field({ key: 'round_size', label: 'Taille des groupes', help: 'Nombre de cartes par groupe. Modifier la taille réorganise les groupes en conservant les réponses.' })}
          {mastery.map(field)}
        </section>
        <section className="study-settings-section"><h3>Modes de réponse</h3>
          {toggle('allow_typed_recall', 'Réponse écrite', 'Écris la réponse puis vérifie-la avec Entrée. La casse et les espaces sont ignorés.')}
          {toggle('allow_multiple_choice', 'Choix multiples', 'Propose des choix pour les cartes nouvelles ou en apprentissage. Un rappel actif reste nécessaire pour la maîtrise.')}
          {toggle('allow_reverse_direction', 'Sens inversé', 'Alterne terme → définition et définition → terme après le nombre de réussites choisi.')}
          {field({ key: 'reverse_after', label: 'Réussites avant le sens inversé', help: 'Nombre de bonnes réponses consécutives avant de proposer le sens inversé, si cette option est activée.' })}
        </section>
        <details className="study-settings-advanced"><summary>Espacement et priorités de sélection</summary>
          <section className="study-settings-section"><h3>Espacement et délais</h3>{spacing.map(field)}</section>
          <section className="study-settings-section"><h3>Priorités et erreurs</h3><p className="setting-tip">Les priorités sont relatives. Le moteur tient aussi compte du score de mémoire et de la dernière apparition.</p>{priorities.map(field)}</section>
        </details>
        <div className="study-settings-footer">
          <button type="button" className="study-settings-defaults" onClick={() => { setDraft({ ...defaults }); setRestored(true) }}><RotateCcw size={16} /><span>Rétablir les paramètres par défaut</span></button>
          {restored && <p role="status" className="setting-tip">Les valeurs d’origine sont prêtes. Enregistre pour les appliquer.</p>}
          <div className="modal-actions"><button type="button" className="secondary-button" onClick={onClose}>Annuler</button><button type="submit" className="primary-button" aria-label="Enregistrer les paramètres">{busy ? 'Enregistrement…' : 'Enregistrer'}</button></div>
        </div>
      </fieldset>
      {error && <p role="alert" className="settings-error">{error}</p>}
    </form>
  </Dialog>
}
