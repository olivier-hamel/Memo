export const clamp = (value: number, minimum: number, maximum: number) => Math.max(minimum, Math.min(maximum, value))
export function stored<T>(key: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(key) || 'null') ?? fallback } catch { return fallback }
}
export function remember(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* The reader also works without storage. */ }
}

