import { createContext, FormEvent, ReactNode, useCallback, useContext, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Inbox, X } from 'lucide-react'
import { ApiError, get } from '../lib/api'
import { initials, localToIso, ROLE_LABELS } from '../lib/format'

// ---------------------------------------------------------------- toast
type Toast = { id: number; text: string; kind: 'ok' | 'error' }
const ToastCtx = createContext<(text: string, kind?: 'ok' | 'error') => void>(() => {})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([])
  const push = useCallback((text: string, kind: 'ok' | 'error' = 'ok') => {
    const id = Date.now() + Math.random()
    setItems((x) => [...x, { id, text, kind }])
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === 'error' ? 7000 : 3500)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.kind === 'error' ? 'error' : ''}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}
export const useToast = () => useContext(ToastCtx)

export function errorText(e: unknown) {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) return e.message
  return 'Something went wrong.'
}

// ---------------------------------------------------------------- basics
export function Spinner() {
  return <div className="spinner" aria-label="Loading" />
}

export function Empty({ text, icon }: { text: string; icon?: ReactNode }) {
  return (
    <div className="empty">
      {icon || <Inbox size={28} />}
      <div>{text}</div>
    </div>
  )
}

export function Avatar({ name, size = '' }: { name?: string; size?: 'sm' | 'lg' | '' }) {
  return (
    <span className={`avatar ${size}`} title={name}>
      {initials(name)}
    </span>
  )
}

export function Person({ m, sub }: { m?: { name: string; role?: string } | null; sub?: boolean }) {
  if (!m) return <span className="muted">Unassigned</span>
  return (
    <span className="flex">
      <Avatar name={m.name} size="sm" />
      <span>
        {m.name}
        {sub && m.role && <div className="muted small">{ROLE_LABELS[m.role] || m.role}</div>}
      </span>
    </span>
  )
}

export function Badge({ children, tone = '' }: { children: ReactNode; tone?: '' | 'dark' | 'outline' | 'warn' | 'danger' }) {
  return <span className={`badge ${tone}`}>{children}</span>
}

export function StatusBadge({ value, labelText }: { value: string; labelText?: string }) {
  const dark = ['won', 'accepted', 'done', 'closed', 'resolved', 'qualified', 'completed', 'active', 'confirmed'].includes(value)
  const warn = ['blocked', 'exception', 'returned', 'overdue', 'critical', 'suspended', 'in_review', 'waiting_customer', 'waiting_internal'].includes(value)
  const outline = ['lost', 'disqualified', 'cancelled', 'nurture'].includes(value)
  const text = labelText || value.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())
  return <Badge tone={dark ? 'dark' : warn ? 'warn' : outline ? 'outline' : ''}>{text}</Badge>
}

export function PageHead({ title, sub, actions }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {sub && <div className="sub">{sub}</div>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  )
}

export function Card({ title, actions, children, pad = true }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; pad?: boolean }) {
  return (
    <div className="card">
      {title && (
        <div className="card-head">
          <h3>{title}</h3>
          {actions && <div className="actions">{actions}</div>}
        </div>
      )}
      {pad ? <div className="card-body">{children}</div> : children}
    </div>
  )
}

export function Tabs({ tabs, value, onChange }: { tabs: { value: string; label: ReactNode }[]; value: string; onChange: (v: string) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.value} role="tab" aria-selected={value === t.value} className={value === t.value ? 'on' : ''} onClick={() => onChange(t.value)}>
          {t.label}
        </button>
      ))}
    </div>
  )
}

export function Segmented({ options, value, onChange }: { options: { value: string; label: ReactNode }[]; value: string; onChange: (v: string) => void }) {
  return (
    <div className="segmented">
      {options.map((o) => (
        <button key={o.value} className={value === o.value ? 'on' : ''} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Pager({ page, count, pageSize = 50, onPage }: { page: number; count: number; pageSize?: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(count / pageSize))
  if (count <= pageSize) return <div className="pager">{count} record{count === 1 ? '' : 's'}</div>
  return (
    <div className="pager">
      <span>
        {count} records · page {page} of {pages}
      </span>
      <span className="flex">
        <button className="btn sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Previous
        </button>
        <button className="btn sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next
        </button>
      </span>
    </div>
  )
}

// ---------------------------------------------------------------- modal
export function Modal({ title, onClose, children, footer, wide }: { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true">
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="icon-btn right" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- members
export type Member = { id: string; name: string; email: string; role: string; status: string; title: string }

export function useMembers() {
  return useQuery({ queryKey: ['members', 'active'], queryFn: () => get<Member[]>('/team/members?active=1'), staleTime: 60_000 })
}

// ---------------------------------------------------------------- form modal
export type FieldDef = {
  name: string
  label: string
  type?: 'text' | 'textarea' | 'date' | 'datetime' | 'number' | 'select' | 'member' | 'email' | 'checkbox' | 'password' | 'multimember'
  options?: { value: string; label: string }[]
  roles?: string[]
  required?: boolean
  hint?: string
  placeholder?: string
  half?: boolean
  show?: (values: Record<string, any>) => boolean
}

export function FieldInput({ def, value, onChange, error }: { def: FieldDef; value: any; onChange: (v: any) => void; error?: string }) {
  const members = useMembers()
  const id = `f-${def.name}`
  let control: ReactNode
  switch (def.type) {
    case 'textarea':
      control = <textarea id={id} className="textarea" value={value ?? ''} placeholder={def.placeholder} onChange={(e) => onChange(e.target.value)} />
      break
    case 'select':
      control = (
        <select id={id} className="select" value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
          <option value="">Choose…</option>
          {(def.options || []).map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      )
      break
    case 'member':
      control = (
        <select id={id} className="select" value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
          <option value="">{def.required ? 'Choose a person…' : 'Nobody'}</option>
          {(members.data || [])
            .filter((m) => !def.roles || def.roles.includes(m.role))
            .map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} · {ROLE_LABELS[m.role] || m.role}
              </option>
            ))}
        </select>
      )
      break
    case 'multimember':
      control = (
        <div className="stack" style={{ maxHeight: 180, overflowY: 'auto' }}>
          {(members.data || [])
            .filter((m) => !def.roles || def.roles.includes(m.role))
            .map((m) => {
              const list: string[] = value || []
              return (
                <label key={m.id} className="check">
                  <input
                    type="checkbox"
                    checked={list.includes(m.id)}
                    onChange={(e) => onChange(e.target.checked ? [...list, m.id] : list.filter((x) => x !== m.id))}
                  />
                  {m.name} <span className="muted small">{ROLE_LABELS[m.role]}</span>
                </label>
              )
            })}
        </div>
      )
      break
    case 'checkbox':
      control = (
        <label className="check">
          <input id={id} type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} /> {def.hint}
        </label>
      )
      break
    default: {
      const t = def.type === 'datetime' ? 'datetime-local' : def.type || 'text'
      control = <input id={id} className="input" type={t} value={value ?? ''} placeholder={def.placeholder} onChange={(e) => onChange(e.target.value)} step={def.type === 'number' ? 'any' : undefined} />
    }
  }
  return (
    <div className={`field ${error ? 'has-err' : ''}`}>
      {def.type !== 'checkbox' && (
        <label htmlFor={id}>
          {def.label}
          {def.required && ' *'}
        </label>
      )}
      {def.type === 'checkbox' && <label>{def.label}</label>}
      {control}
      {def.hint && def.type !== 'checkbox' && <span className="hint">{def.hint}</span>}
      {error && <span className="err">{error}</span>}
    </div>
  )
}

export function FormModal({
  title,
  fields,
  initial = {},
  submitLabel = 'Save',
  onSubmit,
  onClose,
  intro,
  wide,
}: {
  title: ReactNode
  fields: FieldDef[]
  initial?: Record<string, any>
  submitLabel?: string
  onSubmit: (values: Record<string, any>) => Promise<any>
  onClose: () => void
  intro?: ReactNode
  wide?: boolean
}) {
  const [values, setValues] = useState<Record<string, any>>(initial)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const toast = useToast()

  const submit = async (e?: FormEvent) => {
    e?.preventDefault()
    const missing: Record<string, string> = {}
    fields.forEach((f) => {
      if ((f.show ? f.show(values) : true) && f.required && (values[f.name] === undefined || values[f.name] === '' || values[f.name] === null)) {
        missing[f.name] = 'Required'
      }
    })
    if (Object.keys(missing).length) {
      setErrors(missing)
      setMessage('Please fill in the required fields.')
      return
    }
    const out: Record<string, any> = {}
    fields.forEach((f) => {
      let v = values[f.name]
      if (f.type === 'datetime') v = localToIso(v)
      if (v !== undefined) out[f.name] = v
    })
    Object.keys(values).forEach((k) => {
      if (!(k in out)) out[k] = values[k]
    })
    setBusy(true)
    setMessage('')
    try {
      await onSubmit(out)
      onClose()
    } catch (err) {
      if (err instanceof ApiError) {
        const fe: Record<string, string> = {}
        Object.entries(err.fields || {}).forEach(([k, v]) => {
          fe[k] = Array.isArray(v) ? v.join(' ') : String(v)
        })
        setErrors(fe)
        setMessage(err.message)
      } else {
        toast(errorText(err), 'error')
      }
    } finally {
      setBusy(false)
    }
  }

  const visible = fields.filter((f) => (f.show ? f.show(values) : true))
  const rows: FieldDef[][] = []
  visible.forEach((f) => {
    const last = rows[rows.length - 1]
    if (f.half && last && last.length === 1 && last[0].half) last.push(f)
    else rows.push([f])
  })

  return (
    <Modal
      title={title}
      onClose={onClose}
      wide={wide}
      footer={
        <>
          <button className="btn" type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" type="button" disabled={busy} onClick={() => submit()}>
            {busy ? 'Saving…' : submitLabel}
          </button>
        </>
      }
    >
      <form onSubmit={submit}>
        {intro && <div className="notice" style={{ marginBottom: 14 }}>{intro}</div>}
        {message && <div className="notice error" style={{ marginBottom: 14 }}>{message}</div>}
        {rows.map((r, i) => (
          <div className="row" key={i}>
            {r.map((f) => (
              <FieldInput key={f.name} def={f} value={values[f.name]} error={errors[f.name]} onChange={(v) => setValues((x) => ({ ...x, [f.name]: v }))} />
            ))}
          </div>
        ))}
        <button type="submit" hidden />
      </form>
    </Modal>
  )
}

/** Small helper so pages can open a FormModal with one state variable. */
export function useModal<T = any>() {
  const [state, setState] = useState<T | null>(null)
  return { state, open: (s: T) => setState(s), close: () => setState(null) }
}
