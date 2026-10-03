import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { ArrowRight, Flower2, LogOut } from 'lucide-react'
import { apiFetch } from './api'

type User = { username: string; display_name: string; must_change_password: boolean }
type Account = { user: User; logout: () => void; changePassword: () => void }
const AccountContext = createContext<Account | null>(null)
export const useAccount = () => useContext(AccountContext)

export default function AuthGate({ children }: { children: ReactNode }) {
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [user, setUser] = useState<User | null>(null)
  const [changing, setChanging] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const receive = useCallback((data: { enabled: boolean; user: User | null }) => {
    setEnabled(data.enabled)
    setUser(data.user)
    setChanging(false)
  }, [])
  const load = useCallback(async () => {
    try {
      const response = await apiFetch('auth/me', { cache: 'no-store' })
      if (response.status === 401) { receive({ enabled: true, user: null }); return }
      if (!response.ok) throw new Error('Impossible de retrouver ton espace. Réessaie dans un instant.')
      receive(await response.json())
      setError('')
    } catch (caught) { setError((caught as Error).message) }
  }, [receive])

  useEffect(() => {
    void load()
    const expired = () => {
      receive({ enabled: true, user: null })
      setError('Ta session a expiré. Connecte-toi pour reprendre.')
    }
    window.addEventListener('memo:session-expired', expired)
    return () => window.removeEventListener('memo:session-expired', expired)
  }, [load, receive])

  const logout = async () => {
    if (busy) return
    setBusy(true)
    try {
      const response = await apiFetch('auth/logout', { method: 'POST', body: '{}' })
      if (!response.ok) throw new Error('La déconnexion a échoué. Réessaie.')
      receive({ enabled: true, user: null })
      setError('')
    } catch (caught) { setError((caught as Error).message) }
    finally { setBusy(false) }
  }

  if (enabled === false) return <>{children}</>
  const passwordForm = !!user && (!!user.must_change_password || changing)
  if (user && !passwordForm) return <AccountContext.Provider value={{ user, logout: () => void logout(), changePassword: () => { setChanging(true); setError('') } }}>
    {error && <div className="auth-floating-error" role="alert">{error}</div>}
    {children}
  </AccountContext.Provider>

  return <main className="auth-screen">
    <section className="auth-panel" aria-label={passwordForm ? 'Nouveau mot de passe' : 'Connexion'}>
      <div className="brand-mark"><Flower2 size={34} strokeWidth={1.5} /></div>
      <div className="auth-brand">mémo<span>.</span></div>
      <h1>{enabled === null ? 'Ton espace se prépare…' : passwordForm ? 'Un espace bien à toi.' : 'Heureux de te retrouver.'}</h1>
      <p>{passwordForm ? 'Choisis un nouveau mot de passe pour protéger ta progression.' : enabled === null ? 'Un instant, tes cartes t’attendent.' : 'Connecte-toi pour reprendre ton apprentissage à ton rythme.'}</p>
      {error && <div className="auth-error" role="alert">{error}</div>}
      {enabled === null ? error && <button className="primary-button" onClick={() => void load()}>Réessayer</button> : <form key={passwordForm ? 'password' : 'login'} onSubmit={async event => {
        event.preventDefault()
        if (busy) return
        const form = event.currentTarget
        const values = new FormData(form)
        if (passwordForm && values.get('new_password') !== values.get('confirm_password')) { setError('Les nouveaux mots de passe ne correspondent pas.'); return }
        setBusy(true)
        setError('')
        try {
          const body = passwordForm
            ? { current_password: values.get('password'), new_password: values.get('new_password') }
            : { username: values.get('username'), password: values.get('password') }
          const response = await apiFetch(passwordForm ? 'auth/password' : 'auth/login', { method: 'POST', body: JSON.stringify(body) })
          const result = await response.json()
          if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Vérifie les informations saisies.')
          form.reset()
          receive(result)
        } catch (caught) { setError((caught as Error).message) }
        finally { setBusy(false) }
      }}>
        {!passwordForm && <label>Identifiant<input name="username" autoComplete="username" required maxLength={32} autoCapitalize="none" spellCheck={false} disabled={busy} /></label>}
        {passwordForm && <input name="username" type="hidden" value={user?.username} />}
        <label>{passwordForm ? 'Mot de passe actuel' : 'Mot de passe'}<input name="password" type="password" autoComplete="current-password" required maxLength={256} disabled={busy} /></label>
        {passwordForm && <>
          <label>Nouveau mot de passe<input name="new_password" type="password" autoComplete="new-password" required minLength={12} maxLength={256} disabled={busy} /></label>
          <label>Confirmer le nouveau mot de passe<input name="confirm_password" type="password" autoComplete="new-password" required minLength={12} maxLength={256} disabled={busy} /></label>
          <small>Au moins 12 caractères. Une phrase facile à retenir fonctionne bien.</small>
        </>}
        <button className="primary-button" disabled={busy} type="submit">{busy ? 'Un instant…' : passwordForm ? 'Enregistrer le mot de passe' : 'Retrouver mes cartes'}<ArrowRight size={17} /></button>
        {changing && !user?.must_change_password && <button className="auth-secondary" type="button" onClick={() => setChanging(false)} disabled={busy}>Revenir aux cartes</button>}
        {passwordForm && <button className="auth-secondary" type="button" onClick={() => void logout()} disabled={busy}><LogOut size={14} /> Se déconnecter</button>}
      </form>}
      {!passwordForm && enabled && <p className="auth-footnote">Besoin d’un compte ou d’un nouveau mot de passe ? Contacte la personne qui gère cet espace.</p>}
    </section>
  </main>
}
