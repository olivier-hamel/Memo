import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'

async function validationDraft(page: Page) {
  await page.getByRole('button', { name: 'Nouvel ensemble', exact: true }).click()
  await page.getByLabel('Titre de l’ensemble', { exact: true }).fill('Validation du cours')
  await page.getByLabel('Terme 1', { exact: true }).fill('Question du brouillon ?')
  await page.getByLabel('Définition 1', { exact: true }).fill('Réponse non enregistrée.')
  const pdf = await page.request.get('/api/__fixtures/course.pdf')
  await page.getByLabel('Ajouter des documents de référence', { exact: true }).setInputFiles([
    { name: 'Cours.pdf', mimeType: 'application/pdf', buffer: await pdf.body() },
    { name: 'Annexe.pdf', mimeType: 'application/pdf', buffer: await pdf.body() },
  ])
  await expect(page.getByRole('button', { name: 'Validation', exact: true }).first()).toBeEnabled()
}

const validationProposal = { term: 'Quelle information manque ?', definition: 'Une information du cours à apprendre.',
  document_id: '', page: 2, evidence: 'Information dans le cours.', missing_information: 'Absente du brouillon.' }

async function mockValidation(page: Page, outcome: (body: any, attempt: number) => any, deferred = false) {
  const jobs: any[] = []
  const bodies: any[] = []
  const finish = (job: any) => {
    const result = outcome(job.snapshot, bodies.length)
    job.status = result.detail ? 'failed' : 'completed'
    job.error = result.detail || ''
    job.result = result.detail ? null : result
    job.progress = 'Validation terminée'; job.unread = true
  }
  await page.route('**/api/validation-jobs**', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname.split('/validation-jobs')[1]
    const method = route.request().method()
    if (!path && method === 'POST') {
      const body = route.request().postDataJSON(); bodies.push(body)
      const job = { id: `job-${bodies.length}`, title: body.title, set_id: body.set_id, draft_id: body.draft_id,
        snapshot: body, documents: body.document_ids.map((id: string, index: number) => ({ id, name: index ? 'Annexe.pdf' : 'Cours.pdf', kind: 'pdf', page_count: 3 })),
        status: 'running', progress: 'Lecture des documents · 0 / 6 pages', error: '', unread: false, result: null, created_at: Date.now() / 1000, updated_at: Date.now() / 1000 }
      jobs.unshift(job)
      if (!deferred) finish(job)
      return route.fulfill({ status: 202, json: job })
    }
    if (path === '/link') {
      const body = route.request().postDataJSON()
      for (const job of jobs) if (job.draft_id === body.draft_id) { job.set_id = body.set_id; job.snapshot.set_id = body.set_id }
      return route.fulfill({ json: { jobs } })
    }
    if (!path) return route.fulfill({ json: { jobs } })
    const job = jobs.find(item => item.id === path.split('/')[1])
    if (path.endsWith('/read')) { job.unread = false; return route.fulfill({ json: job }) }
    return route.fulfill({ json: job })
  })
  return { jobs, bodies, finish: () => finish(jobs[0]) }
}

async function reviewValidation(page: Page) {
  await page.locator('.validation-sidebar').getByRole('button').first().click()
  return page.getByRole('dialog', { name: 'Validation des cartes' })
}

const covered = { covered: true, proposals: [], checked_pages: 6, checked_cards: 1 }

test('validation runs in the background, leaves editing available and notifies on completion', async ({ page }) => {
  const mock = await mockValidation(page, () => covered, true)
  await validationDraft(page)
  await page.getByRole('button', { name: 'Validation', exact: true }).first().click()
  await expect(page.getByRole('dialog', { name: 'Validation des cartes' })).toHaveCount(0)
  await expect(page.getByLabel('Terme 1', { exact: true })).toBeEnabled()
  await expect(page.locator('.validation-sidebar')).toContainText('Lecture des documents')
  expect(mock.bodies[0].cards).toEqual([{ term: 'Question du brouillon ?', definition: 'Réponse non enregistrée.' }])
  expect(mock.bodies[0].document_ids).toHaveLength(2)
  const running = await reviewValidation(page)
  await expect(running).toContainText('Tu peux fermer cette fenêtre')
  await running.getByRole('button', { name: 'Continuer en arrière-plan' }).click()
  mock.finish()
  await expect(page.locator('.validation-toast')).toContainText('Validation terminée', { timeout: 10000 })
  await page.locator('.validation-toast').getByRole('button', { name: 'Voir les résultats' }).click()
  const dialog = page.getByRole('dialog', { name: 'Validation des cartes' })
  await expect(dialog).toContainText('Aucun manque détecté')
  await dialog.getByRole('button', { name: 'Terminer' }).click()
  await expect(page.getByLabel('Terme 2', { exact: true })).toHaveCount(0)
})

test('background validation accepts or refuses proposals and saves only accepted cards', async ({ page }) => {
  await mockValidation(page, body => ({ covered: false, checked_pages: 6, checked_cards: 1, proposals: [
    { ...validationProposal, document_id: body.document_ids[0] },
    { ...validationProposal, term: 'Proposition refusée ?', definition: 'Réponse refusée.', document_id: body.document_ids[0] },
  ] }))
  await validationDraft(page)
  await page.getByRole('button', { name: 'Validation', exact: true }).last().click()
  const dialog = await reviewValidation(page)
  await expect(dialog.getByRole('button', { name: 'Accepter', exact: true })).toHaveCount(2)
  await page.screenshot({ path: test.info().outputPath('validation-desktop.png') })
  await dialog.getByRole('button', { name: 'Accepter', exact: true }).first().click()
  await expect(dialog).toContainText('Acceptée')
  await dialog.getByRole('button', { name: 'Refuser', exact: true }).click()
  await expect(dialog).toContainText('Refusée')
  await dialog.getByRole('button', { name: 'Terminer' }).click()
  await expect(page.getByLabel('Terme 2', { exact: true })).toHaveValue(validationProposal.term)
  await expect(page.getByLabel('Terme 3', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Créer l’ensemble', exact: true }).first().click()
  await expect(page.locator('.version-badge')).toHaveText('Version 1')
  const id = new URL(page.url()).hash.slice(1).split('/')[1]
  const saved = await (await page.request.get(`/api/sets/${id}`)).json()
  expect(saved.cards).toEqual([{ term: 'Question du brouillon ?', definition: 'Réponse non enregistrée.' },
    { term: validationProposal.term, definition: validationProposal.definition }])
  const reopened = await reviewValidation(page)
  await expect(reopened.getByRole('button', { name: 'Accepter', exact: true })).toHaveCount(0)
})

test('failed background validation keeps its result accessible and can retry', async ({ page }) => {
  await mockValidation(page, (_, attempt) => attempt === 1 ? { detail: 'L’IA n’a pas pu vérifier tous les documents.' } : covered)
  await validationDraft(page)
  await page.getByRole('button', { name: 'Validation', exact: true }).first().click()
  const dialog = await reviewValidation(page)
  await expect(dialog.getByRole('alert')).toContainText('tous les documents')
  await expect(dialog).not.toContainText('Aucun manque détecté')
  await dialog.getByRole('button', { name: 'Réessayer' }).click()
  await expect(dialog).toHaveCount(0)
  await reviewValidation(page)
  await expect(dialog).toContainText('Aucun manque détecté')
  await dialog.getByRole('button', { name: 'Terminer' }).click()
  await expect(page.getByLabel('Définition 1', { exact: true })).toHaveValue('Réponse non enregistrée.')
})

test('background status and review fit mobile and can refuse all proposals', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockValidation(page, body => ({ covered: false, checked_pages: 6, checked_cards: 1,
    proposals: [{ ...validationProposal, document_id: body.document_ids[0] }] }))
  await validationDraft(page)
  await page.getByRole('button', { name: 'Validation', exact: true }).last().click()
  const dialog = await reviewValidation(page)
  await expect(dialog.getByRole('button', { name: 'Tout refuser' })).toBeVisible()
  expect(await dialog.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true)
  await page.screenshot({ path: test.info().outputPath('validation-mobile.png') })
  await dialog.getByRole('button', { name: 'Tout refuser' }).click()
  await dialog.getByRole('button', { name: 'Terminer' }).click()
  await expect(page.getByLabel('Terme 2', { exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('background results cannot confirm coverage with missing pages or an inconsistent result', async ({ page }) => {
  const results = [
    { covered: true, proposals: [], checked_pages: 3, checked_cards: 1 },
    { covered: true, proposals: [], checked_pages: 6, checked_cards: 0 },
    { covered: true, proposals: [] },
    { covered: true, proposals: [validationProposal], checked_pages: 6, checked_cards: 1 }, covered,
  ]
  await mockValidation(page, () => results.shift())
  await validationDraft(page)
  await page.getByRole('button', { name: 'Validation', exact: true }).first().click()
  const dialog = await reviewValidation(page)
  for (let attempt = 0; attempt < 4; attempt++) {
    await expect(dialog.getByRole('alert')).toBeVisible()
    await expect(dialog).not.toContainText('Aucun manque détecté')
    await dialog.getByRole('button', { name: 'Réessayer' }).click()
    await expect(dialog).toHaveCount(0)
    await reviewValidation(page)
  }
  await expect(dialog).toContainText('Aucun manque détecté')
})

test('background validation survives navigation and reload and can restore its unsaved draft', async ({ page }) => {
  const mock = await mockValidation(page, body => ({ covered: false, checked_pages: 6, checked_cards: 1,
    proposals: [{ ...validationProposal, document_id: body.document_ids[0] }] }), true)
  await validationDraft(page)
  await page.getByRole('button', { name: 'Validation', exact: true }).first().click()
  await page.locator('.collection-sidebar').getByRole('button', { name: 'Mes ensembles', exact: true }).click()
  await page.getByRole('button', { name: 'Quitter sans enregistrer' }).click()
  await expect(page.getByRole('heading', { name: 'Mes ensembles.' })).toBeVisible()
  await expect(page.locator('.validation-sidebar')).toContainText('Lecture des documents')
  await page.reload()
  await expect(page.locator('.validation-sidebar')).toContainText('Lecture des documents')
  mock.finish()
  await expect(page.locator('.validation-toast')).toContainText('Validation terminée', { timeout: 10000 })
  let dialog = await reviewValidation(page)
  await expect(dialog.getByRole('button', { name: 'Accepter', exact: true })).toBeDisabled()
  await dialog.getByRole('button', { name: 'Retrouver le brouillon' }).click()
  await expect(page.getByLabel('Titre de l’ensemble', { exact: true })).toHaveValue('Validation du cours')
  await expect(page.getByLabel('Définition 1', { exact: true })).toHaveValue('Réponse non enregistrée.')
  await page.reload()
  dialog = page.getByRole('dialog', { name: 'Validation des cartes' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Fermer', exact: true }).click()
  await expect(page.getByLabel('Définition 1', { exact: true })).toHaveValue('Réponse non enregistrée.')
  dialog = await reviewValidation(page)
  await dialog.getByRole('button', { name: 'Accepter', exact: true }).click()
  await dialog.getByRole('button', { name: 'Terminer' }).click()
  await expect(page.getByLabel('Terme 2', { exact: true })).toHaveValue(validationProposal.term)
  expect(mock.bodies).toHaveLength(1)
})

test('background completion appears while studying and proposals preserve later card edits', async ({ page }) => {
  const mock = await mockValidation(page, body => ({ covered: false, checked_pages: 6, checked_cards: 1,
    proposals: [{ ...validationProposal, document_id: body.document_ids[0] }] }), true)
  await validationDraft(page)
  await page.getByRole('button', { name: 'Créer l’ensemble', exact: true }).first().click()
  await expect(page.locator('.version-badge')).toHaveText('Version 1')
  await page.getByRole('button', { name: 'Validation', exact: true }).first().click()
  await page.getByRole('button', { name: 'Étudier cet ensemble', exact: true }).click()
  await expect(page.locator('.sidebar .validation-sidebar')).toContainText('Lecture des documents', { timeout: 15000 })
  mock.finish()
  await expect(page.locator('.validation-toast')).toContainText('Validation terminée', { timeout: 10000 })
  let dialog = await reviewValidation(page)
  await expect(dialog.getByRole('button', { name: 'Accepter', exact: true })).toBeDisabled()
  await dialog.getByRole('button', { name: 'Ouvrir l’ensemble', exact: true }).click()
  await page.getByLabel('Définition 1', { exact: true }).fill('Ma nouvelle réponse, modifiée après le lancement.')
  dialog = await reviewValidation(page)
  await dialog.getByRole('button', { name: 'Accepter', exact: true }).click()
  await dialog.getByRole('button', { name: 'Terminer' }).click()
  await expect(page.getByLabel('Définition 1', { exact: true })).toHaveValue('Ma nouvelle réponse, modifiée après le lancement.')
  await expect(page.getByLabel('Terme 2', { exact: true })).toHaveValue(validationProposal.term)
  expect(mock.bodies).toHaveLength(1)
})

async function studyState(page: Page) {
  const [, id, version] = new URL(page.url()).hash.slice(1).split('/')
  return (await page.request.get(`/api/state?set_id=${encodeURIComponent(id)}&version=${version}`)).json()
}

async function chooseDocument(page: Page, name: string) {
  await page.getByRole('button', { name: 'Choisir un document', exact: true }).click()
  const picker = page.getByRole('dialog', { name: 'Choisir un document', exact: true })
  await picker.getByRole('button', { name: `Consulter ${name}`, exact: true }).click()
  await expect(picker).toHaveCount(0)
}

const password = 'browser-test-passphrase-123'
test.beforeEach(async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Identifiant', { exact: true }).fill('browser_oli')
  await page.getByLabel('Mot de passe', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Retrouver mes cartes' }).click()
  await expect(page.getByRole('heading', { name: 'Mes ensembles.' })).toBeVisible()
  await expect(page.locator('.collection-topbar')).toHaveCount(0)
})

test('reference courses preserve notes, drafts, resized panels and reading position', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.getByRole('button', { name: 'Nouvel ensemble' }).click()
  await page.getByLabel('Titre de l’ensemble', { exact: true }).fill('Cours avec documents')
  await page.getByLabel('Terme 1', { exact: true }).fill('Brouillon conservé')
  await page.getByLabel('Définition 1', { exact: true }).fill('Ma réponse')
  const pptx = await page.request.get('/api/__fixtures/course.pptx')
  const pdf = await page.request.get('/api/__fixtures/course.pdf')
  expect((await pdf.body()).subarray(0, 5).toString()).toBe('%PDF-')
  expect((await pptx.body()).subarray(0, 2).toString()).toBe('PK')
  await page.getByLabel('Ajouter des documents de référence', { exact: true }).setInputFiles([
    { name: 'Cours.pptx', mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation', buffer: await pptx.body() },
    { name: 'Chapitre.pdf', mimeType: 'application/pdf', buffer: await pdf.body() },
  ])
  await expect(page.getByRole('button', { name: 'Ajout en cours…' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Créer l’ensemble', exact: true }).first()).toBeDisabled()
  await page.getByLabel('Définition 1', { exact: true }).fill('Ma réponse pendant la conversion')
  await expect(page.getByRole('button', { name: 'Choisir un document', exact: true })).toBeVisible({ timeout: 30000 })
  await expect(page.locator('.reference-choice-heading')).toContainText('2 documents', { timeout: 30000 })
  const sidebar = page.locator('.collection-sidebar')
  await expect(sidebar).toHaveCSS('width', '72px')
  await expect(sidebar.getByRole('button', { name: 'Mes ensembles', exact: true })).toBeVisible()
  await expect(sidebar.getByRole('button', { name: 'Créer un ensemble', exact: true })).toHaveAttribute('title', 'Créer un ensemble')
  await expect(sidebar.getByRole('button', { name: 'Se déconnecter', exact: true })).toBeVisible()
  await chooseDocument(page, 'Cours.pptx')
  await expect(page.getByRole('button', { name: 'Slide suivante', exact: true })).toBeEnabled()
  await expect(page.getByLabel('Notes du présentateur — Slide 1', { exact: true })).toHaveCount(0)
  await expect(page.getByLabel('Commentaires — Slide 1', { exact: true })).toHaveCount(0)
  await expect(page.locator('.reference-editor .presenter-notes')).toHaveCount(0)
  await page.getByRole('button', { name: 'Slide suivante', exact: true }).click()
  await expect(page.getByLabel('Lecteur de documents', { exact: true }).getByLabel('Notes du présentateur — Slide 2', { exact: true })).toContainText('Notes de la première slide.')
  await expect(page.getByLabel('Commentaires — Slide 2', { exact: true })).toContainText('Professeur')
  await expect(page.getByLabel('Commentaires — Slide 2', { exact: true })).toContainText('Préciser cet exemple.')
  const readerBox = (await page.getByLabel('Lecteur de documents', { exact: true }).boundingBox())!
  expect(readerBox.y).toBe(0)
  expect(readerBox.x + readerBox.width).toBe(1440)
  expect(readerBox.height).toBe(1100)
  const reader = page.getByLabel('Lecteur de documents', { exact: true })
  await expect(reader.getByRole('button', { name: 'Choisir un document', exact: true })).toBeVisible()
  await expect(reader.getByRole('button', { name: 'Masquer le lecteur', exact: true })).toHaveCount(0)
  await expect(reader.getByRole('button', { name: 'Ajouter des documents', exact: true })).toHaveCount(0)
  await expect(reader.getByRole('button', { name: 'Slide suivante', exact: true })).toBeVisible()
  await expect(reader.getByRole('button', { name: 'Zoomer', exact: true })).toBeVisible()
  await expect(page.locator('.reference-editor .reference-management')).toHaveCount(0)
  const controlsBox = (await reader.locator('.reference-management').boundingBox())!
  const documentBox = (await reader.locator('.reference-scroll').boundingBox())!
  expect(controlsBox.x).toBeGreaterThanOrEqual(readerBox.x)
  expect(controlsBox.x + controlsBox.width).toBeLessThanOrEqual(readerBox.x + readerBox.width)
  expect(controlsBox.y + controlsBox.height).toBeLessThanOrEqual(documentBox.y)
  const slideNotes = page.getByLabel('Notes du présentateur — Slide 2', { exact: true })
  await expect(slideNotes).toBeVisible()
  const slideBox = (await page.locator('.reference-page[data-page="2"]').boundingBox())!
  const notesBox = (await slideNotes.boundingBox())!
  expect(notesBox.y).toBeGreaterThanOrEqual(slideBox.y + slideBox.height)
  await expect(slideNotes).toHaveCSS('max-height', 'none')
  await page.screenshot({ path: test.info().outputPath('reader-desktop.png') })
  await page.getByRole('button', { name: 'Slide suivante', exact: true }).click()
  await expect(page.getByLabel('Lecteur de documents', { exact: true }).getByLabel('Notes du présentateur — Slide 3', { exact: true })).toContainText('Notes de la slide masquée.')
  await expect(page.getByLabel('Commentaires — Slide 3', { exact: true })).toContainText('Commentaire sur la slide masquée.')
  await expect(page.getByLabel('Commentaires — Slide 3', { exact: true })).toContainText('Réponse de Étudiant')
  await expect(page.getByLabel('Commentaires — Slide 3', { exact: true })).toContainText('Bien compris.')
  await page.getByRole('button', { name: 'Slide précédente', exact: true }).click()
  await expect(page.getByLabel('Numéro de slide', { exact: true })).toHaveValue('2')
  await expect.poll(() => page.locator('.reference-page[data-page="2"] canvas').evaluate(canvas => (canvas as HTMLCanvasElement).width)).toBeGreaterThan(0)
  await page.getByRole('button', { name: 'Zoomer', exact: true }).click()
  await expect(page.getByRole('button', { name: '110 %', exact: true })).toBeVisible()
  await chooseDocument(page, 'Chapitre.pdf')
  await expect(page.getByRole('button', { name: 'Page suivante', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'Page suivante', exact: true }).click()
  await page.getByRole('button', { name: 'Page suivante', exact: true }).click()
  await expect(page.getByLabel('Numéro de page', { exact: true })).toHaveValue('3')
  await chooseDocument(page, 'Cours.pptx')
  await expect(page.getByLabel('Numéro de slide', { exact: true })).toHaveValue('2')
  await expect(page.getByRole('button', { name: '110 %', exact: true })).toBeVisible()
  await expect(page.getByLabel('Définition 1', { exact: true })).toHaveValue('Ma réponse pendant la conversion')
  const divider = page.getByRole('separator', { name: 'Largeur du panneau de cartes' })
  const bounds = (await divider.boundingBox())!
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2)
  await page.mouse.down()
  await page.mouse.move(bounds.x + 110, bounds.y + bounds.height / 2, { steps: 12 })
  await page.mouse.up()
  const ratio = await divider.getAttribute('aria-valuenow')
  expect(Number(ratio)).toBeGreaterThan(50)
  await expect(page.getByLabel('Terme 1', { exact: true })).toHaveValue('Brouillon conservé')
  await divider.focus(); await divider.press('ArrowLeft')
  await expect(divider).toHaveAttribute('aria-valuenow', String(Number(ratio) - 2))
  await page.getByRole('button', { name: 'Créer l’ensemble', exact: true }).first().click()
  await expect(page.locator('.version-badge')).toHaveText('Version 1')
  await expect(page.getByLabel('Numéro de slide', { exact: true })).toHaveValue('2')
  await page.reload()
  await expect(page.getByLabel('Numéro de slide', { exact: true })).toHaveValue('2')
  await expect(page.getByLabel('Lecteur de documents', { exact: true }).getByLabel('Notes du présentateur — Slide 2', { exact: true })).toContainText('Notes de la première slide.')
  await expect(page.getByLabel('Commentaires — Slide 2', { exact: true })).toContainText('Professeur')
  await expect(page.getByLabel('Commentaires — Slide 2', { exact: true })).toContainText('Préciser cet exemple.')
  await expect(divider).toHaveAttribute('aria-valuenow', String(Number(ratio) - 2))
  await page.getByRole('button', { name: 'Fermer le lecteur de documents', exact: true }).click()
  await expect(sidebar).toHaveCSS('width', '226px')
  await expect(page.getByLabel('Terme 1', { exact: true })).toHaveValue('Brouillon conservé')
  await page.getByRole('button', { name: 'Afficher le lecteur', exact: true }).click()
  await expect(sidebar).toHaveCSS('width', '72px')
  await chooseDocument(page, 'Chapitre.pdf')
  await expect(page.getByLabel('Numéro de page', { exact: true })).toHaveValue('3')
  await page.getByRole('button', { name: 'Fermer le lecteur de documents', exact: true }).click()
  await expect(page.getByLabel('Lecteur de documents', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Afficher le lecteur', exact: true }).click()
  await expect(page.locator('.reference-choice-heading')).toContainText('2 documents')
  await expect(page.getByLabel('Numéro de page', { exact: true })).toHaveValue('3')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Choisir un document', exact: true }).click()
  const picker = page.getByRole('dialog', { name: 'Choisir un document', exact: true })
  await expect(picker.getByRole('listitem')).toHaveCount(2)
  await expect(picker.locator('.is-current')).toContainText('Chapitre.pdf')
  await page.screenshot({ path: test.info().outputPath('document-picker-desktop.png') })
  await picker.press('Escape')
  await expect(picker).toHaveCount(0)
  await expect(page.getByLabel('Numéro de page', { exact: true })).toHaveValue('3')
  await page.getByRole('button', { name: 'Choisir un document', exact: true }).click()
  await picker.getByRole('button', { name: 'Supprimer Chapitre.pdf', exact: true }).click()
  await expect(picker.getByRole('listitem')).toHaveCount(1)
  await picker.getByRole('button', { name: 'Annuler', exact: true }).click()
  await expect(picker.getByRole('listitem')).toHaveCount(2)
  await picker.getByRole('button', { name: 'Supprimer Chapitre.pdf', exact: true }).click()
  await picker.getByRole('button', { name: 'Fermer la fenêtre', exact: true }).click()
  await expect(page.getByLabel('Numéro de slide', { exact: true })).toHaveValue('2')
  await expect(page.getByLabel('Définition 1', { exact: true })).toHaveValue('Ma réponse pendant la conversion')
  await page.getByRole('button', { name: 'Enregistrer', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Enregistrer', exact: true })).toBeDisabled()
  await page.reload()
  await page.getByRole('button', { name: 'Choisir un document', exact: true }).click()
  await expect(picker.getByRole('listitem')).toHaveCount(1)
  await expect(picker.getByRole('button', { name: 'Consulter Cours.pptx', exact: true })).toBeVisible()
  await picker.getByRole('button', { name: 'Supprimer Cours.pptx', exact: true }).click()
  await expect(picker).toContainText('Aucun document pour le moment.')
  await picker.getByRole('button', { name: 'Annuler', exact: true }).click()
  await expect(picker.getByRole('listitem')).toHaveCount(1)
  await picker.getByRole('button', { name: 'Supprimer Cours.pptx', exact: true }).click()
  await picker.getByRole('button', { name: 'Fermer la fenêtre', exact: true }).click()
  await expect(page.getByLabel('Lecteur de documents', { exact: true })).toHaveCount(0)
  await expect(sidebar).toHaveCSS('width', '226px')
  await expect(page.getByLabel('Terme 1', { exact: true })).toHaveValue('Brouillon conservé')
  await page.getByRole('button', { name: 'Enregistrer', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Enregistrer', exact: true })).toBeDisabled()
  await page.reload()
  await page.getByRole('button', { name: 'Choisir un document', exact: true }).click()
  await expect(picker).toContainText('Aucun document pour le moment.')
  await picker.getByRole('button', { name: 'Fermer la fenêtre', exact: true }).click()
  await expect(page.locator('.version-badge')).toHaveText('Version 1')
  expect(errors).toEqual([])
})

test('mobile reference reader switches panels and failed uploads preserve the draft', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 844 })
  await page.getByRole('button', { name: 'Nouvel ensemble' }).click()
  await page.getByLabel('Terme 1', { exact: true }).fill('Mobile sans perte')
  const pdf = await page.request.get('/api/__fixtures/course.pdf')
  await page.getByLabel('Ajouter des documents de référence', { exact: true }).setInputFiles({ name: 'Cours.pdf', mimeType: 'application/pdf', buffer: await pdf.body() })
  await expect(page.getByRole('button', { name: 'Document', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Document', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Page suivante', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'Page suivante', exact: true }).click()
  await page.getByRole('button', { name: 'Cartes', exact: true }).click()
  await expect(page.getByLabel('Terme 1', { exact: true })).toHaveValue('Mobile sans perte')
  await page.getByLabel('Définition 1', { exact: true }).fill('Texte mobile')
  await page.getByRole('button', { name: 'Document', exact: true }).click()
  await expect(page.getByLabel('Numéro de page', { exact: true })).toHaveValue('2')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: test.info().outputPath('reader-mobile.png') })
  await page.getByLabel('Ajouter des documents de référence', { exact: true }).setInputFiles({ name: 'Cassé.pdf', mimeType: 'application/pdf', buffer: Buffer.from('not a PDF') })
  await expect(page.getByRole('alert')).toContainText('PDF valide')
  await page.getByRole('button', { name: 'Choisir un document', exact: true }).click()
  const picker = page.getByRole('dialog', { name: 'Choisir un document', exact: true })
  await expect(picker.getByRole('listitem')).toHaveCount(1)
  await page.screenshot({ path: test.info().outputPath('document-picker-mobile.png') })
  await picker.getByRole('button', { name: 'Fermer la fenêtre', exact: true }).click()
  await page.getByRole('button', { name: 'Cartes', exact: true }).click()
  await expect(page.getByLabel('Définition 1', { exact: true })).toHaveValue('Texte mobile')
  const pptx = await page.request.get('/api/__fixtures/course.pptx')
  await page.getByLabel('Ajouter des documents de référence', { exact: true }).setInputFiles({ name: 'Cours.pptx', mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation', buffer: await pptx.body() })
  await expect(page.locator('.reference-choose')).toContainText('Cours.pptx', { timeout: 30000 })
  await page.getByRole('button', { name: 'Document', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Slide suivante', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'Slide suivante', exact: true }).click()
  const notes = page.getByLabel('Lecteur de documents', { exact: true }).getByLabel('Notes du présentateur — Slide 2', { exact: true })
  await expect(notes).toBeVisible()
  await expect(notes).toContainText('Notes de la première slide.')
  await expect(page.locator('.reference-editor .presenter-notes')).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: test.info().outputPath('reader-mobile-powerpoint-notes.png') })
})

test('create, study, edit and resume an earlier version with its progress', async ({ page, context }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.getByRole('button', { name: 'Nouvel ensemble' }).click()
  await page.getByLabel('Titre de l’ensemble', { exact: true }).fill('Mon ensemble navigateur')
  await page.getByLabel('Terme 1', { exact: true }).fill('Première question')
  await page.getByLabel('Définition 1', { exact: true }).fill('Première réponse')
  await page.getByRole('button', { name: 'Ajouter une carte' }).click()
  await page.getByLabel('Terme 2', { exact: true }).fill('Deuxième question')
  await page.getByLabel('Définition 2', { exact: true }).fill('Deuxième réponse')
  await page.getByRole('button', { name: 'Créer l’ensemble', exact: true }).first().click()
  await page.getByRole('button', { name: 'Étudier cet ensemble', exact: true }).click()
  await expect(page.locator('.sidebar-deck h3')).toHaveText('Mon ensemble navigateur')
  await page.getByRole('button', { name: 'Révéler la réponse' }).click()
  await page.getByRole('button', { name: 'Bien retenu' }).click()
  await expect.poll(async () => (await studyState(page)).correct).toBe(1)
  await page.reload()
  await expect.poll(async () => (await studyState(page)).correct).toBe(1)
  await page.locator('.sidebar').getByRole('button', { name: 'Voir l’ensemble', exact: true }).click()
  await page.getByRole('textbox', { name: 'Définition 1', exact: true }).fill('Réponse modifiée')
  await page.getByRole('button', { name: 'Enregistrer', exact: true }).click()
  await page.getByRole('button', { name: 'Étudier cet ensemble', exact: true }).click()
  await expect(page.locator('.cover-index')).toHaveText('VERSION 2')
  expect((await studyState(page)).correct).toBe(0)
  await page.locator('.sidebar').getByRole('button', { name: 'Voir l’ensemble', exact: true }).click()
  await page.getByLabel('Version de Mon ensemble navigateur', { exact: true }).selectOption('1')
  await page.getByRole('button', { name: 'Étudier cet ensemble', exact: true }).click()
  await expect(page.locator('.cover-index')).toHaveText('VERSION 1')
  await expect.poll(async () => (await studyState(page)).correct).toBe(1)

  const other = await context.browser()!.newContext()
  const max = await other.newPage()
  await max.goto('http://127.0.0.1:8885/')
  await max.getByLabel('Identifiant', { exact: true }).fill('browser_max')
  await max.getByLabel('Mot de passe', { exact: true }).fill(password)
  await max.getByRole('button', { name: 'Retrouver mes cartes' }).click()
  await expect(max.getByRole('heading', { name: 'Mes ensembles.' })).toBeVisible()
  await expect(max.getByRole('heading', { name: 'Mon ensemble navigateur', exact: true })).toHaveCount(0)
  await expect(max.getByRole('heading', { name: 'Éthique de l’ingénieur', exact: true })).toBeVisible()
  expect(errors).toEqual([])
  await other.close()
})

test('mobile editor, card removal and duplicate validation', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 })
  await page.getByRole('button', { name: 'Nouvel ensemble' }).click()
  await page.getByLabel('Titre de l’ensemble', { exact: true }).fill('Validation mobile')
  await page.getByLabel('Terme 1', { exact: true }).fill('Identique')
  await page.getByLabel('Définition 1', { exact: true }).fill('Identique')
  await page.getByRole('button', { name: 'Ajouter une carte' }).click()
  await page.getByLabel('Terme 2', { exact: true }).fill('Identique')
  await page.getByLabel('Définition 2', { exact: true }).fill('Identique')
  await page.getByRole('button', { name: 'Créer l’ensemble', exact: true }).first().click()
  await expect(page.getByRole('alert')).toContainText('identiques')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Supprimer la carte 2' }).click()
  await expect(page.getByLabel('Terme 2', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Créer l’ensemble', exact: true }).first().click()
  await expect(page.locator('.version-badge')).toHaveText('Version 1')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  const sidebar = page.locator('.collection-sidebar')
  await expect(sidebar.getByRole('button', { name: 'Changer mon mot de passe' })).toBeVisible()
  await sidebar.getByRole('button', { name: 'Se déconnecter' }).click()
  await expect(page.getByLabel('Identifiant', { exact: true })).toBeVisible()
})

const quizletImport = {
  title: 'Vocabulaire importé', description: 'Depuis un ensemble public',
  cards: [{ term: 'Bonjour', definition: 'Hello' }, { term: 'Merci', definition: 'Thank you\nThanks' }],
}

test('Quizlet import fills editable cards and saves through the normal set flow', async ({ page }) => {
  let release!: () => void
  const ready = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/sets/import/quizlet', async route => {
    expect(route.request().postDataJSON()).toEqual({ url: 'https://quizlet.com/123/test-flash-cards/' })
    await ready
    await route.fulfill({ json: quizletImport })
  })
  await page.getByRole('button', { name: 'Nouvel ensemble' }).click()
  await page.getByRole('button', { name: 'Importer depuis Quizlet' }).click()
  await page.getByLabel('Lien public Quizlet').fill('https://quizlet.com/123/test-flash-cards/')
  await page.getByLabel('Lien public Quizlet').press('Enter')
  await expect(page.getByRole('button', { name: 'Import en cours…' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Créer l’ensemble', exact: true }).first()).toBeDisabled()
  release()
  await expect(page.getByLabel('Titre de l’ensemble', { exact: true })).toHaveValue(quizletImport.title)
  await expect(page.getByLabel('Description (facultative)', { exact: true })).toHaveValue(quizletImport.description)
  await expect(page.getByLabel('Terme 1', { exact: true })).toHaveValue('Bonjour')
  await expect(page.getByLabel('Définition 2', { exact: true })).toHaveValue('Thank you\nThanks')
  await expect(page.locator('.quizlet-import-notice')).toContainText('2 cartes importées')
  await expect(page.locator('.version-badge')).toHaveCount(0)
  await page.getByLabel('Définition 1', { exact: true }).fill('Salut')
  await page.getByRole('button', { name: 'Créer l’ensemble', exact: true }).first().click()
  await expect(page.locator('.version-badge')).toHaveText('Version 1')
  await expect(page.getByRole('button', { name: 'Importer depuis Quizlet' })).toHaveCount(0)
  await expect(page.getByLabel('Définition 1', { exact: true })).toHaveValue('Salut')
  await page.getByRole('button', { name: 'Étudier cet ensemble', exact: true }).click()
  await expect(page.locator('.sidebar-deck h3')).toHaveText(quizletImport.title)
})

test('mobile Quizlet import preserves existing draft cards and metadata', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 })
  await page.route('**/api/sets/import/quizlet', route => route.fulfill({ json: quizletImport }))
  await page.getByRole('button', { name: 'Nouvel ensemble' }).click()
  await page.getByLabel('Titre de l’ensemble', { exact: true }).fill('Mon titre')
  await page.getByLabel('Description (facultative)', { exact: true }).fill('Ma description')
  await page.getByLabel('Terme 1', { exact: true }).fill('Ma question')
  await page.getByRole('button', { name: 'Importer depuis Quizlet' }).click()
  await page.getByLabel('Lien public Quizlet').fill('https://quizlet.com/123/test-flash-cards/')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Importer les cartes' }).click()
  await expect(page.locator('.quizlet-import-notice')).toContainText('2 cartes importées')
  await expect(page.getByLabel('Titre de l’ensemble', { exact: true })).toHaveValue('Mon titre')
  await expect(page.getByLabel('Description (facultative)', { exact: true })).toHaveValue('Ma description')
  await expect(page.getByLabel('Terme 1', { exact: true })).toHaveValue('Ma question')
  await expect(page.getByLabel('Définition 1', { exact: true })).toHaveValue('')
  await expect(page.getByLabel('Terme 2', { exact: true })).toHaveValue('Bonjour')
  await expect(page.getByLabel('Terme 3', { exact: true })).toHaveValue('Merci')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('Quizlet import errors keep the draft intact and allow retry', async ({ page }) => {
  let attempt = 0
  await page.route('**/api/sets/import/quizlet', route => {
    attempt++
    return route.fulfill(attempt === 1 ? { status: 422, json: { detail: 'Cet ensemble Quizlet est introuvable ou privé. Vérifie le lien public.' } } : { json: quizletImport })
  })
  await page.getByRole('button', { name: 'Nouvel ensemble' }).click()
  await page.getByLabel('Terme 1', { exact: true }).fill('Question conservée')
  await page.getByRole('button', { name: 'Importer depuis Quizlet' }).click()
  await page.getByLabel('Lien public Quizlet').fill('https://quizlet.com/123/test-flash-cards/')
  await page.getByRole('button', { name: 'Importer les cartes' }).click()
  await expect(page.getByRole('alert')).toContainText('introuvable ou privé')
  await expect(page.getByLabel('Terme 1', { exact: true })).toHaveValue('Question conservée')
  await expect(page.getByLabel('Terme 2', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Importer les cartes' }).click()
  await expect(page.locator('.quizlet-import-notice')).toContainText('2 cartes importées')
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByLabel('Terme 1', { exact: true })).toHaveValue('Question conservée')
})

test('Quizlet imports cannot overflow the card limit or introduce duplicate draft cards', async ({ page }) => {
  let attempt = 0
  await page.route('**/api/sets/import/quizlet', route => {
    attempt++
    return route.fulfill({ json: attempt === 1 ? { ...quizletImport, cards: Array.from({ length: 300 }, (_, index) => ({ term: `Term ${index}`, definition: `Definition ${index}` })) } : quizletImport })
  })
  await page.getByRole('button', { name: 'Nouvel ensemble' }).click()
  await page.getByLabel('Terme 1', { exact: true }).fill('Bonjour')
  await page.getByLabel('Définition 1', { exact: true }).fill('Hello')
  await page.getByRole('button', { name: 'Importer depuis Quizlet' }).click()
  await page.getByLabel('Lien public Quizlet').fill('https://quizlet.com/123/test-flash-cards/')
  await page.getByRole('button', { name: 'Importer les cartes' }).click()
  await expect(page.getByRole('alert')).toContainText('limite de 300 cartes')
  await page.getByRole('button', { name: 'Importer les cartes' }).click()
  await expect(page.getByRole('alert')).toContainText('doublons')
  await expect(page.getByLabel('Terme 1', { exact: true })).toHaveValue('Bonjour')
  await expect(page.getByLabel('Terme 2', { exact: true })).toHaveCount(0)
  await expect(page.locator('.quizlet-import-notice')).toHaveCount(0)
})
