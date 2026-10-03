export const memoBase = import.meta.env.BASE_URL

export function apiFetch(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers)
  if (init.method && init.method !== 'GET') {
    headers.set('Content-Type', 'application/json')
    headers.set('X-Memo-Request', '1')
  }
  return fetch(`${memoBase}api/${path}`, { ...init, headers, credentials: 'same-origin' }).then(response => {
    if (response.status === 401 && !path.startsWith('auth/')) window.dispatchEvent(new Event('memo:session-expired'))
    return response
  })
}
