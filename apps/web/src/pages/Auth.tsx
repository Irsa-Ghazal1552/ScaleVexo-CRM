import { FormEvent, ReactNode, useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { ShieldCheck } from 'lucide-react'
import { ApiError, ensureCsrf, get, post } from '../lib/api'
import { useAuth } from '../lib/auth'
import { errorText } from '../components/ui'

function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="auth-page">
      <div className="auth-side">
        <div className="flex">
          <span className="brand-mark">S</span>
          <b style={{ fontSize: 17 }}>ScaleVexo CRM</b>
        </div>
        <div>
          <h2>One record of what was promised, who owns the next step, and whether it happened.</h2>
          <p>Leads, deals, onboarding, projects and support in one continuous journey - for the whole ScaleVexo team.</p>
        </div>
        <span style={{ color: '#6b6b6b', fontSize: 12 }}>Internal pilot · Release 1</span>
      </div>
      <div className="auth-form">{children}</div>
    </div>
  )
}

export function LoginPage() {
  const qc = useQueryClient()
  const nav = useNavigate()
  const [params] = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [mfa, setMfa] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    ensureCsrf()
  }, [])

  const done = async () => {
    await qc.invalidateQueries({ queryKey: ['me'] })
    nav(params.get('next') && params.get('next') !== '/login' ? params.get('next')! : '/', { replace: true })
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      if (!mfa) {
        const res = await post('/auth/login', { email, password })
        if (res?.mfa_required) {
          setMfa(true)
          return
        }
      } else {
        await post('/auth/mfa-verify', { code })
      }
      await done()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell>
      <form onSubmit={submit}>
        <h1>{mfa ? 'Verification code' : 'Sign in'}</h1>
        <p className="muted" style={{ marginBottom: 20 }}>
          {mfa ? 'Enter the 6-digit code from your authenticator app.' : 'Access is by invitation only.'}
        </p>
        {error && <div className="notice error" style={{ marginBottom: 14 }}>{error}</div>}
        {!mfa ? (
          <>
            <div className="field">
              <label htmlFor="email">Work email</label>
              <input id="email" className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
            </div>
            <div className="field">
              <label htmlFor="password">Password</label>
              <input id="password" className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
          </>
        ) : (
          <div className="field">
            <label htmlFor="code">Code</label>
            <input id="code" className="input" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} required autoFocus />
          </div>
        )}
        <button className="btn primary" style={{ width: '100%', justifyContent: 'center', height: 42 }} disabled={busy}>
          {busy ? 'Please wait…' : mfa ? 'Verify' : 'Sign in'}
        </button>
      </form>
    </AuthShell>
  )
}

export function AcceptInvitePage() {
  const { token } = useParams()
  const qc = useQueryClient()
  const nav = useNavigate()
  const [info, setInfo] = useState<{ email: string; role: string; workspace: string } | null>(null)
  const [error, setError] = useState('')
  const [form, setForm] = useState({ first_name: '', last_name: '', password: '', confirm: '' })
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    ensureCsrf()
    get(`/invitations/${token}`)
      .then(setInfo)
      .catch((e) => setError(errorText(e)))
  }, [token])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (form.password !== form.confirm) {
      setError('The passwords do not match.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await post(`/invitations/${token}`, form)
      await qc.invalidateQueries({ queryKey: ['me'] })
      nav('/', { replace: true })
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell>
      <form onSubmit={submit}>
        <h1>Join {info?.workspace || 'the workspace'}</h1>
        {info && (
          <p className="muted" style={{ marginBottom: 18 }}>
            {info.email} · {info.role}
          </p>
        )}
        {error && <div className="notice error" style={{ marginBottom: 14 }}>{error}</div>}
        {info && (
          <>
            <div className="row">
              <div className="field">
                <label>First name</label>
                <input className="input" value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} required />
              </div>
              <div className="field">
                <label>Last name</label>
                <input className="input" value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
              </div>
            </div>
            <div className="field">
              <label>Password</label>
              <input className="input" type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
              <span className="hint">At least 10 characters, not only numbers.</span>
            </div>
            <div className="field">
              <label>Confirm password</label>
              <input className="input" type="password" autoComplete="new-password" value={form.confirm} onChange={(e) => setForm({ ...form, confirm: e.target.value })} required />
            </div>
            <button className="btn primary" style={{ width: '100%', justifyContent: 'center', height: 42 }} disabled={busy}>
              {busy ? 'Creating account…' : 'Create account'}
            </button>
          </>
        )}
      </form>
    </AuthShell>
  )
}

export function MfaPanel({ onDone }: { onDone?: () => void }) {
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null)
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const { refresh } = useAuth()

  const start = async () => {
    setError('')
    try {
      setSetup(await post('/auth/mfa/setup'))
    } catch (e) {
      setError(errorText(e))
    }
  }
  const enable = async () => {
    setError('')
    try {
      await post('/auth/mfa/enable', { code })
      await refresh()
      onDone?.()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : errorText(e))
    }
  }
  return (
    <div className="stack">
      {error && <div className="notice error">{error}</div>}
      {!setup ? (
        <button className="btn primary" onClick={start}>
          <ShieldCheck size={16} /> Set up authenticator app
        </button>
      ) : (
        <>
          <div className="notice">
            1. Open Google Authenticator, Microsoft Authenticator or 1Password.
            <br />
            2. Add an account using this setup key: <code className="k">{setup.secret}</code>
            <br />
            <span className="small muted">
              (Or paste this link into an app that accepts it: <code className="k">{setup.otpauth_uri}</code>)
            </span>
          </div>
          <div className="field">
            <label htmlFor="mfa-code">3. Enter the 6-digit code shown in the app</label>
            <input id="mfa-code" className="input" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />
          </div>
          <button className="btn primary" onClick={enable}>
            Turn on MFA
          </button>
        </>
      )}
    </div>
  )
}

export function MfaSetupPage({ forced }: { forced?: boolean }) {
  const { logout } = useAuth()
  return (
    <AuthShell>
      <div style={{ width: '100%', maxWidth: 420 }}>
        <h1>Protect your account</h1>
        <p className="muted" style={{ marginBottom: 18 }}>
          {forced ? 'Owners and administrators must use multi-factor authentication before continuing.' : 'Add a second step to your sign-in.'}
        </p>
        <MfaPanel onDone={() => (window.location.href = '/')} />
        <button className="btn ghost" style={{ marginTop: 16 }} onClick={logout}>
          Sign out
        </button>
      </div>
    </AuthShell>
  )
}
