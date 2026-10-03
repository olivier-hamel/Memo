import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'

async function studyState(page: Page) {
  const [, id, version] = new URL(page.url()).hash.slice(1).split('/')
  return (await page.request.get(`/api/state?set_id=${encodeURIComponent(id)}&version=${version}`)).json()
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
