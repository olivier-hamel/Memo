export type CardState = 'NEW' | 'UNTESTED' | 'LEARNING' | 'FAMILIAR' | 'MASTERED'
export type RoundStatus = 'LOCKED' | 'ACTIVE' | 'COMPLETED'
export type Mode = 'LEARN'
export type CardInput = { term: string; definition: string }
export type CardSet = {
  id: string; title: string; description: string; editable: boolean; shared: boolean
  revision: string; latest_version: number; versions: { version: number; card_count: number }[]
}
export type ReferenceDocument = { id: string; name: string; kind: 'pdf' | 'ppt' | 'pptx'; page_count: number }
export type SlideComment = { author: string; text: string; replies: { author: string; text: string }[] }
export type CardSetDetail = CardSet & { version: number; cards: CardInput[]; documents?: ReferenceDocument[] }
export type SetSelection = { id: string; version: number; title: string }
export interface StudyConfig {
  round_size: number
  mastery_threshold: number
  minimum_successful_recalls: number
  minimum_active_recall_successes: number
  minimum_spaced_recalls: number
  minimum_spacing_questions: number
  minimum_spacing: number
  weight_new: number
  weight_learning: number
  weight_familiar: number
  weight_mastered: number
  incorrect_answer_penalty: number
  familiar_after: number
  reverse_after: number
  allow_reverse_direction: boolean
  allow_multiple_choice: boolean
  allow_typed_recall: boolean
  review_interval: number
  learning_interval: number
}
export interface StudyState {
  revision: string
  mode: Mode
  phase: 'INITIAL_ROUND_LEARNING' | 'FINAL_MASTERY_ROUND' | 'COMPLETE'
  total: number
  initial_mastered: number
  final_mastered: number
  progress: number
  active_round_index: number
  active_mastered: number
  active_total: number
  complete: boolean
  correct: number
  wrong: number
  streak: number
  review_available: boolean
  due_reviews: number
  next_review_at: number | null
  typed_recall: boolean
  round_size: number
  config: StudyConfig
  default_config: StudyConfig
  notice: string
  rounds: { id: number; status: RoundStatus; total: number; mastered: number }[]
  final_status: RoundStatus
  active_cards: { id: string; term: string; state: CardState; score: number }[]
  question: {
    card_id: string
    kind: 'typed' | 'free_recall' | 'multiple_choice'
    options: string[]
    direction: 'forward' | 'reverse'
    text: string
    showing_answer: boolean
    answered: boolean
    correct: boolean | null
    historical: boolean
    typed_response: string
    can_grade: boolean
    can_previous: boolean
    position: number
    history_length: number
    state: CardState
    score: number
  } | null
}
export type Action =
  | { type: 'flip' | 'reset' | 'refresh' }
  | { type: 'grade'; correct: boolean }
  | { type: 'navigate'; direction: -1 | 1; response: string }
  | { type: 'typed'; response: string }
  | { type: 'choice'; choice: number }
  | { type: 'mode'; mode: Mode }
  | { type: 'settings'; typed: boolean }
  | { type: 'settings'; config: StudyConfig }
  | { type: 'settings'; defaults: true }
