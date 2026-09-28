import { ReactNode, useId, useState } from 'react'
import { Link } from 'react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle, Ban, CalendarClock, Check, CheckCircle2, Clock3, Linkedin, Mail, MessageSquare, Pencil, Phone, Sparkles,
  StickyNote, Users as UsersIcon,
} from 'lucide-react'
import { ApiError, get, Paged, patch, post } from '../lib/api'
import { useMe } from '../lib/auth'
import { ACTIVITY_KINDS, entityPath, fmtDateTime, inHours, localToIso, relative, toLocalInput } from '../lib/format'
import { Badge, Empty, errorText, FormModal, Person, Spinner, useModal, useToast } from './ui'

// ---------------------------------------------------------------- tasks (CRM05)
export type Task = {
  id: string
  title: string
  description: string
  kind: 'follow_up' | 'task'
  status: string
  owner: { id: string; name: string; role: string }
  due_at: string
  original_due_at: string
  reschedule_count: number
  overdue: boolean
  outcome: string
  stop_reason: string
  blocked_reason: string
  created_by_rule: string
  context: { type: string; id: string; label: string; customer: string; stage?: string } | null
  reschedules: { id: string; from_due: string; to_due: string; reason: string; actor: any; created_at: string }[]
  version: number
}

export function TaskRow({ task, showOwner, onChanged }: { task: Task; showOwner?: boolean; onChanged: () => void }) {
  const modal = useModal<'complete' | 'reschedule' | 'block' | 'cancel' | 'history'>()
  const toast = useToast()
  const act = async (action: string, body: any) => {
    const res = await post(`/tasks/${task.id}/${action}`, { version: task.version, ...body })
    onChanged()
    return res
  }
  const open = task.status === 'open' || task.status === 'blocked'
  return (
    <div className="task">
      <div className="tl-icon" style={{ background: task.overdue ? '#111' : undefined, color: task.overdue ? '#fff' : undefined }}>
        {task.status === 'done' ? <Check size={16} /> : task.status === 'blocked' ? <Ban size={16} /> : <Clock3 size={16} />}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="ttl">
          {task.title} {task.created_by_rule && <Badge tone="outline">Rule {task.created_by_rule}</Badge>}
        </div>
        <div className="meta">
          <span className={task.overdue ? 'overdue' : ''}>
            {task.overdue ? 'Overdue · ' : 'Due '}
            {fmtDateTime(task.due_at)} ({relative(task.due_at)})
          </span>
          {task.reschedule_count > 0 && (
            <a className="link" role="button" onClick={() => modal.open('history')}>
              Rescheduled {task.reschedule_count}× · originally {fmtDateTime(task.original_due_at)}
            </a>
          )}
          {task.context && (
            <Link className="link" to={entityPath(task.context.type, task.context.id)}>
              {task.context.customer !== task.context.label ? `${task.context.customer} · ` : ''}
              {task.context.label}
            </Link>
          )}
          {showOwner && <Person m={task.owner} />}
          {task.status === 'blocked' && <Badge tone="warn">Blocked: {task.blocked_reason}</Badge>}
          {task.status === 'done' && <span>Outcome: {task.outcome}</span>}
        </div>
      </div>
      {open && (
        <div className="acts">
          {task.status === 'open' ? (
            <>
              <button className="btn sm primary" onClick={() => modal.open('complete')}>
                <CheckCircle2 size={14} /> Complete
              </button>
              <button className="btn sm" onClick={() => modal.open('reschedule')}>
                <CalendarClock size={14} /> Reschedule
              </button>
              <button className="btn sm ghost" onClick={() => modal.open('block')}>
                Block
              </button>
            </>
          ) : (
            <button
              className="btn sm"
              onClick={() =>
                act('unblock', {})
                  .then(() => toast('Task unblocked'))
                  .catch((e) => toast(errorText(e), 'error'))
              }
            >
              Unblock
            </button>
          )}
          <button className="btn sm ghost" onClick={() => modal.open('cancel')}>
            Cancel
          </button>
        </div>
      )}
      {modal.state === 'complete' && (
        <FormModal
          title="Complete task"
          intro={task.kind === 'follow_up' ? 'Record what happened, then schedule the next step or say why you are stopping.' : undefined}
          fields={[
            { name: 'outcome', label: 'Outcome', type: 'textarea', required: true },
            { name: 'next_action', label: 'Next action', placeholder: 'e.g. Send proposal', half: true },
            { name: 'next_action_due', label: 'Next action due', type: 'datetime', half: true, show: (v) => !!v.next_action },
            { name: 'stop_reason', label: 'Or: reason to stop following up', show: (v) => task.kind === 'follow_up' && !v.next_action },
          ]}
          initial={{ next_action_due: inHours(48) }}
          submitLabel="Complete"
          onClose={modal.close}
          onSubmit={(v) => act('complete', v).then(() => toast('Task completed'))}
        />
      )}
      {modal.state === 'reschedule' && (
        <FormModal
          title="Reschedule"
          intro="The original deadline stays on record."
          fields={[
            { name: 'due_at', label: 'New due time', type: 'datetime', required: true },
            { name: 'reason', label: 'Reason', required: true },
          ]}
          initial={{ due_at: toLocalInput(new Date(Math.max(Date.now(), new Date(task.due_at).getTime()) + 86400000).toISOString()) }}
          onClose={modal.close}
          onSubmit={(v) => act('reschedule', v).then(() => toast('Rescheduled'))}
        />
      )}
      {modal.state === 'block' && (
        <FormModal
          title="Mark as blocked"
          fields={[{ name: 'reason', label: 'What is blocking it?', type: 'textarea', required: true }]}
          onClose={modal.close}
          onSubmit={(v) => act('block', v)}
        />
      )}
      {modal.state === 'cancel' && (
        <FormModal
          title="Cancel task"
          fields={[{ name: 'reason', label: 'Reason', required: true }]}
          submitLabel="Cancel task"
          onClose={modal.close}
          onSubmit={(v) => act('cancel', v)}
        />
      )}
      {modal.state === 'history' && (
        <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && modal.close()}>
          <div className="modal">
            <div className="modal-head">
              <h2>Reschedule history</h2>
            </div>
            <div className="modal-body">
              {task.reschedules.map((r) => (
                <div key={r.id} className="tl-item">
                  <div className="tl-body">
                    <div>
                      {fmtDateTime(r.from_due)} → <b>{fmtDateTime(r.to_due)}</b>
                    </div>
                    <div className="tl-meta">
                      {r.reason} · {r.actor?.name} · {fmtDateTime(r.created_at)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <div className="modal-foot">
              <button className="btn" onClick={modal.close}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export function TaskList({ filter, title = 'Tasks', linkTo }: { filter: Record<string, string>; title?: string; linkTo?: Record<string, string> }) {
  const qc = useQueryClient()
  const me = useMe()
  const key = ['tasks', filter]
  const q = useQuery({ queryKey: key, queryFn: () => get<Paged<Task>>('/tasks?' + new URLSearchParams({ status: 'open,blocked', ...filter })) })
  const [adding, setAdding] = useState(false)
  const toast = useToast()
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['tasks'] })
    qc.invalidateQueries({ queryKey: ['today'] })
  }
  return (
    <div className="card">
      <div className="card-head">
        <h3>{title}</h3>
        <div className="actions">
          <button className="btn sm" onClick={() => setAdding(true)}>
            + Task
          </button>
        </div>
      </div>
      {q.isLoading ? <Spinner /> : q.data?.results.length ? q.data.results.map((t) => <TaskRow key={t.id} task={t} showOwner onChanged={refresh} />) : <Empty text="No open tasks." />}
      {adding && (
        <FormModal
          title="New task"
          fields={[
            { name: 'title', label: 'Title', required: true },
            { name: 'kind', label: 'Type', type: 'select', options: [{ value: 'follow_up', label: 'Follow-up' }, { value: 'task', label: 'Task' }], half: true },
            { name: 'due_at', label: 'Due', type: 'datetime', required: true, half: true },
            { name: 'owner_id', label: 'Owner', type: 'member', required: true },
            { name: 'description', label: 'Details', type: 'textarea' },
          ]}
          initial={{ kind: 'follow_up', due_at: inHours(24), owner_id: me.membership.id }}
          onClose={() => setAdding(false)}
          onSubmit={(v) =>
            post('/tasks', { ...v, ...(linkTo || {}) }).then(() => {
              toast('Task created')
              refresh()
            })
          }
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------- activities (CRM04)
const KIND_ICON: Record<string, ReactNode> = {
  call: <Phone size={15} />,
  email: <Mail size={15} />,
  meeting: <UsersIcon size={15} />,
  linkedin: <Linkedin size={15} />,
  note: <StickyNote size={15} />,
}

export type Activity = {
  id: string
  kind: string
  kind_label: string
  subject: string
  outcome: string
  body: string
  occurred_at: string
  recorded_at: string
  author: { id: string; name: string } | null
  verification: string
  verification_label: string
  next_action: string
  corrected: boolean
  revisions: { id: string; previous: any; reason: string; editor: any; created_at: string }[]
  links: Record<string, string>
  source_url?: string
}

export function Timeline({ target, allowLog = true, extraTop }: { target: { lead_id?: string; opportunity_id?: string; client_id?: string }; allowLog?: boolean; extraTop?: ReactNode }) {
  const qc = useQueryClient()
  const me = useMe()
  const toast = useToast()
  const fid = useId()
  const filterKey = target.opportunity_id ? { opportunity: target.opportunity_id } : target.lead_id ? { lead: target.lead_id } : { client: target.client_id! }
  const q = useQuery({ queryKey: ['activities', filterKey], queryFn: () => get<Paged<Activity>>('/activities?' + new URLSearchParams(filterKey as any)) })
  const [kind, setKind] = useState('call')
  const [form, setForm] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [editing, setEditing] = useState<Activity | null>(null)
  const [correcting, setCorrecting] = useState<Activity | null>(null)

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['activities'] })
    qc.invalidateQueries({ queryKey: ['tasks'] })
    qc.invalidateQueries({ queryKey: ['lead'] })
    qc.invalidateQueries({ queryKey: ['deal'] })
  }

  const save = async () => {
    setBusy(true)
    setErr('')
    try {
      await post('/activities', { kind, ...target, ...form, next_action_due: localToIso(form.next_action_due), occurred_at: localToIso(form.occurred_at) })
      setForm({})
      toast('Activity logged')
      refresh()
    } catch (e) {
      setErr(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  const isManager = me.capabilities.sales_manage

  return (
    <div className="card">
      {allowLog && (
        <div className="composer">
          <div className="composer-tabs">
            {ACTIVITY_KINDS.map((k) => (
              <button key={k.value} className={kind === k.value ? 'on' : ''} onClick={() => setKind(k.value)}>
                {k.label}
              </button>
            ))}
          </div>
          <div className="card-body">
            {err && <div className="notice error" style={{ marginBottom: 10 }}>{err}</div>}
            {kind !== 'note' && (
              <div className="row">
                <div className="field">
                  <label htmlFor={`${fid}-outcome`}>Outcome *</label>
                  <input id={`${fid}-outcome`} className="input" placeholder={kind === 'call' ? 'e.g. Spoke - interested, wants proposal' : 'What happened?'} value={form.outcome || ''} onChange={(e) => setForm({ ...form, outcome: e.target.value })} />
                </div>
                <div className="field" style={{ maxWidth: 220 }}>
                  <label htmlFor={`${fid}-when`}>When</label>
                  <input id={`${fid}-when`} className="input" type="datetime-local" value={form.occurred_at || ''} onChange={(e) => setForm({ ...form, occurred_at: e.target.value })} />
                </div>
              </div>
            )}
            <div className="field">
              <label htmlFor={`${fid}-body`}>{kind === 'note' ? 'Note *' : 'Notes'}</label>
              <textarea id={`${fid}-body`} className="textarea" style={{ minHeight: 64 }} value={form.body || ''} onChange={(e) => setForm({ ...form, body: e.target.value })} />
            </div>
            {kind === 'linkedin' && (
              <div className="field">
                <label htmlFor={`${fid}-link`}>Profile / message link</label>
                <input id={`${fid}-link`} className="input" value={form.source_url || ''} onChange={(e) => setForm({ ...form, source_url: e.target.value })} />
              </div>
            )}
            <div className="row">
              <div className="field">
                <label htmlFor={`${fid}-next`}>Next action</label>
                <input id={`${fid}-next`} className="input" placeholder="Creates a follow-up for you" value={form.next_action || ''} onChange={(e) => setForm({ ...form, next_action: e.target.value })} />
              </div>
              <div className="field" style={{ maxWidth: 220 }}>
                <label htmlFor={`${fid}-due`}>Due</label>
                <input id={`${fid}-due`} className="input" type="datetime-local" value={form.next_action_due || ''} onChange={(e) => setForm({ ...form, next_action_due: e.target.value })} />
              </div>
            </div>
            <div className="flex">
              <span className="muted small">Manual entries are recorded as self-reported.</span>
              <button className="btn primary right" onClick={save} disabled={busy}>
                {busy ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
      {extraTop}
      <div className="timeline">
        {q.isLoading && <Spinner />}
        {q.data?.results.length === 0 && <Empty text="No activity yet." icon={<MessageSquare size={26} />} />}
        {q.data?.results.map((a) => (
          <div className="tl-item" key={a.id}>
            <div className="tl-icon">{KIND_ICON[a.kind]}</div>
            <div className="tl-body">
              <div className="flex wrap">
                <b>{a.kind_label}</b>
                {a.outcome && <span>· {a.outcome}</span>}
                <Badge tone={a.verification === 'provider_confirmed' ? 'dark' : 'outline'}>{a.verification_label}</Badge>
                {a.corrected && <Badge tone="warn">Corrected</Badge>}
              </div>
              {a.body && <div className="pre" style={{ marginTop: 4 }}>{a.body}</div>}
              {a.source_url && (
                <a className="link small" href={a.source_url} target="_blank" rel="noreferrer">
                  {a.source_url}
                </a>
              )}
              {a.next_action && <div className="small" style={{ marginTop: 4 }}>Next: {a.next_action}</div>}
              <div className="tl-meta" style={{ marginTop: 4 }}>
                <span>{a.author?.name}</span>
                <span title={`Recorded ${fmtDateTime(a.recorded_at)}`}>{fmtDateTime(a.occurred_at)}</span>
                {Object.entries(a.links).map(([k, v]) => (
                  <span key={k}>
                    {k}: {v}
                  </span>
                ))}
                {(a.author?.id === me.membership.id || isManager) && (
                  <button className="btn ghost sm" onClick={() => setEditing(a)}>
                    <Pencil size={12} /> Correct
                  </button>
                )}
                {a.author?.id === me.membership.id && !isManager && (
                  <button className="btn ghost sm" onClick={() => setCorrecting(a)}>
                    Request time correction
                  </button>
                )}
              </div>
              {a.revisions.length > 0 && (
                <details className="small muted" style={{ marginTop: 4 }}>
                  <summary>Correction trail ({a.revisions.length})</summary>
                  {a.revisions.map((r) => (
                    <div key={r.id} className="source">
                      {fmtDateTime(r.created_at)} by {r.editor?.name}: {r.reason}
                      <div>Previous: {r.previous.outcome || r.previous.body || r.previous.subject}</div>
                    </div>
                  ))}
                </details>
              )}
            </div>
          </div>
        ))}
      </div>
      {editing && (
        <FormModal
          title="Correct activity"
          intro="The original version is kept in the correction trail."
          fields={[
            { name: 'outcome', label: 'Outcome' },
            { name: 'body', label: 'Notes', type: 'textarea' },
            ...(isManager ? [{ name: 'occurred_at', label: 'When it happened', type: 'datetime' as const }] : []),
            { name: 'reason', label: 'Reason for correction', required: true },
          ]}
          initial={{ outcome: editing.outcome, body: editing.body, occurred_at: toLocalInput(editing.occurred_at) }}
          onClose={() => setEditing(null)}
          onSubmit={(v) => {
            const body: any = { ...v }
            if (!isManager) delete body.occurred_at
            if (body.occurred_at) body.occurred_at = localToIso(body.occurred_at)
            return patch(`/activities/${editing.id}`, body).then(() => {
              toast('Correction saved')
              refresh()
            })
          }}
        />
      )}
      {correcting && (
        <FormModal
          title="Request a correction"
          intro="Historical times cannot be rewritten by the author. Your manager will review this request."
          fields={[
            { name: 'requested_value', label: 'Correct time', type: 'datetime', required: true },
            { name: 'reason', label: 'Reason', required: true },
          ]}
          onClose={() => setCorrecting(null)}
          onSubmit={(v) =>
            post('/corrections', {
              entity_type: 'activity',
              entity_id: correcting.id,
              field: 'occurred_at',
              current_value: correcting.occurred_at,
              requested_value: v.requested_value,
              reason: v.reason,
            }).then(() => toast('Correction request sent'))
          }
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------- AI assistance (CRM12)
export function AIPanel({ entityType, entityId, allowDraft = true }: { entityType: 'lead' | 'opportunity' | 'client'; entityId: string; allowDraft?: boolean }) {
  const [result, setResult] = useState<any>(null)
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const [draft, setDraft] = useState({ subject: '', body: '' })
  const [instructions, setInstructions] = useState('')
  const toast = useToast()
  const qc = useQueryClient()

  const run = async (feature: 'summarize' | 'draft-followup') => {
    setBusy(feature)
    setErr('')
    setResult(null)
    try {
      const res = await post(`/ai/${feature}`, { entity_type: entityType, entity_id: entityId, instructions })
      setResult(res)
      if (feature === 'draft-followup') setDraft({ subject: res.output.subject, body: res.output.body })
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : errorText(e))
    } finally {
      setBusy('')
    }
  }

  const decide = async (decision: string) => {
    if (!result) return
    await post(`/ai/requests/${result.request_id}/decision`, { decision }).catch(() => {})
  }

  const saveAsNote = async () => {
    const text = result.feature === 'summarize' ? result.output.summary + '\n' + (result.output.key_points || []).map((p: string) => '• ' + p).join('\n') : `Draft follow-up (not sent)\nSubject: ${draft.subject}\n\n${draft.body}`
    const target = entityType === 'lead' ? { lead_id: entityId } : entityType === 'opportunity' ? { opportunity_id: entityId } : { client_id: entityId }
    try {
      await post('/activities', { kind: 'note', body: text, ...target })
      await decide(result.feature === 'draft_followup' && (draft.body !== result.output.body || draft.subject !== result.output.subject) ? 'edited' : 'accepted')
      qc.invalidateQueries({ queryKey: ['activities'] })
      toast('Saved to the timeline as a note')
      setResult(null)
    } catch (e) {
      toast(errorText(e), 'error')
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <h3 className="flex">
          <Sparkles size={16} /> AI assistant
        </h3>
        <div className="actions">
          <button className="btn sm" disabled={!!busy} onClick={() => run('summarize')}>
            {busy === 'summarize' ? 'Working…' : 'Summarize notes'}
          </button>
          {allowDraft && (
            <button className="btn sm" disabled={!!busy} onClick={() => run('draft-followup')}>
              {busy === 'draft-followup' ? 'Working…' : 'Draft follow-up'}
            </button>
          )}
        </div>
      </div>
      <div className="card-body">
        {!result && !err && (
          <div className="stack">
            <span className="muted small">Uses only the notes on this record. Nothing is sent or changed automatically.</span>
            {allowDraft && <input className="input" placeholder="Optional instructions for the draft (tone, focus)…" value={instructions} onChange={(e) => setInstructions(e.target.value)} />}
          </div>
        )}
        {err && <div className="notice">{err}</div>}
        {result && (
          <div className="ai-box stack">
            {result.feature === 'summarize' ? (
              <>
                <h4>Summary</h4>
                <div>{result.output.summary}</div>
                {result.output.key_points?.length > 0 && (
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {result.output.key_points.map((p: string, i: number) => (
                      <li key={i}>{p}</li>
                    ))}
                  </ul>
                )}
                {result.output.open_questions?.length > 0 && (
                  <div className="small">
                    <b>Open questions:</b> {result.output.open_questions.join(' ')}
                  </div>
                )}
              </>
            ) : (
              <>
                <h4>Draft follow-up (review before sending yourself)</h4>
                {result.output.warnings?.map((w: string) => (
                  <div key={w} className="notice error">
                    <AlertTriangle size={14} /> {w}
                  </div>
                ))}
                <input className="input" value={draft.subject} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} />
                <textarea className="textarea" style={{ minHeight: 160 }} value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
              </>
            )}
            <details className="small">
              <summary>Source notes used ({result.sources.length})</summary>
              {result.sources.map((s: any) => (
                <div className="source" key={s.id}>
                  {s.date} · {s.kind}: {s.text}
                </div>
              ))}
            </details>
            <div className="flex wrap">
              <span className="muted small">
                {result.provider === 'mock' ? 'Offline test provider' : 'Claude'} · cost ${result.cost_usd}
              </span>
              <span className="right flex">
                {result.feature === 'draft_followup' && (
                  <button
                    className="btn sm"
                    onClick={() => {
                      navigator.clipboard?.writeText(`${draft.subject}\n\n${draft.body}`)
                      decide(draft.body !== result.output.body ? 'edited' : 'accepted')
                      toast('Copied - paste it into your email')
                    }}
                  >
                    Copy
                  </button>
                )}
                <button className="btn sm" onClick={saveAsNote}>
                  Save as note
                </button>
                <button
                  className="btn sm ghost"
                  onClick={() => {
                    decide('rejected')
                    setResult(null)
                  }}
                >
                  Reject
                </button>
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- stage bar
export function StageBar({ stages, current, onPick, doneUntil }: { stages: { value: string; label: string }[]; current: string; onPick?: (v: string) => void; doneUntil?: number }) {
  const idx = stages.findIndex((s) => s.value === current)
  const limit = doneUntil ?? idx
  return (
    <div className="stagebar" role="group" aria-label="Stages">
      {stages.map((s, i) => (
        <button
          key={s.value}
          className={s.value === current ? 'current' : i < limit ? 'done' : ''}
          onClick={() => onPick && s.value !== current && onPick(s.value)}
          title={onPick ? `Move to ${s.label}` : s.label}
          aria-current={s.value === current ? 'step' : undefined}
          disabled={!onPick}
        >
          {s.label}
        </button>
      ))}
    </div>
  )
}

export function History({ items }: { items: { id: string; from_stage: string; to_stage: string; reason: string; actor: any; created_at: string }[] }) {
  if (!items?.length) return <Empty text="No changes yet." />
  return (
    <div className="timeline">
      {items.map((h) => (
        <div className="tl-item" key={h.id}>
          <div className="tl-body">
            <div>
              {h.from_stage ? `${h.from_stage} → ` : ''}
              <b>{h.to_stage}</b>
            </div>
            <div className="tl-meta">
              {h.actor?.name} · {fmtDateTime(h.created_at)} {h.reason && `· ${h.reason}`}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
