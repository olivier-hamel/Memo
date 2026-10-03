import { apiFetch } from './api'

export class LibraryError extends Error {
  constructor(message: string, public status: number) { super(message) }
}

export async function readLibrary<T>(path: string, body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await apiFetch(path, body === undefined ? { cache: 'no-store' } : { method: 'POST', body: JSON.stringify(body) })
  } catch {
    throw new LibraryError('La connexion a été interrompue. Réessaie dans un instant.', 0)
  }
  const data = await response.json()
  if (!response.ok) throw new LibraryError(typeof data.detail === 'string' ? data.detail : 'Vérifie les informations saisies.', response.status)
  return data as T
}
