import { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Lock, Plus, Users } from 'lucide-react'
import { get, Paged, patch, post, qs } from '../lib/api'
import { fmtDateTime, inHours, relative, SEVERITIES } from '../lib/format'
import { Badge, Card, Empty, errorText, FieldDef, FormModal, PageHead, Pager, Person, Segmented, Spinner, StatusBadge, useToast } from '../components/ui'
import { TaskList } from '../components/work'

function SeverityBadge({ s }: { s: string }) {
  return <Badge tone={s === 'critical' ? 'danger' : s === 'high' ? 'warn' : s === 'medium' ? '' : 'outline'}>{s}</Badge>
}

export function TicketsPage() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const [params] = useSearchParams()
  const [filter, setFilter] = useState('open')
  const [mine, setMine] = useState('')
  const [q, setQ] = useState(params.get('q') || '')
  const [page, setPage] = useState(1)
  const [creating, setCreating] = useState(false)
  const list = useQuery({
    queryKey: ['tickets', filter, mine, q, page],
    queryFn: () => get<Paged<any>>('/tickets' + qs({ open: filter === 'open' ? 1 : '', status: filter === 'closed' ? 'resolved,closed' : '', owner: mine, q, page })),
  })
  const projects = useQuery({ queryKey: ['projects-all'], queryFn: () => get<Paged<any>>('/projects?page_size=500'), enabled: creating })
  const clients = useQuery({ queryKey: ['clients-all'], queryFn: () => get<Paged<any>>('/clients?page_size=500'), enabled: creating })
  return (
    <>
      <PageHead
        title="Tickets"
        sub="Client requests and internal issues, each with an owner, next action and resolution evidence."
        actions={
          <button className="btn primary" onClick={() => setCreating(true)}>
            <Plus size={16} /> Ticket
          </button>
        }
      />
      <div className="toolbar">
        <input className="input grow" placeholder="Search tickets or #number…" defaultValue={q} onKeyDown={(e) => e.key === 'Enter' && setQ((e.target as HTMLInputElement).value)} />
        <Segmented options={[{ value: 'open', label: 'Open' }, { value: 'closed', label: 'Resolved' }, { value: 'all', label: 'All' }]} value={filter} onChange={(v) => { setFilter(v); setPage(1) }} />
        <Segmented options={[{ value: '', label: 'Everyone' }, { value: 'me', label: 'Mine' }]} value={mine} onChange={setMine} />
      </div>
      <div className="table-wrap">
        {list.isLoading ? (
          <Spinner />
        ) : !list.data?.results.length ? (
          <Empty text="No tickets here." />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>#</th>
                <th>Ticket</th>
                <th>Severity</th>
                <th>Status</th>
                <th>Owner</th>
                <th>Next action</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {list.data.results.map((t) => (
                <tr key={t.id} className="click" onClick={() => nav(`/tickets/${t.id}`)}>
                  <td className="muted">{t.number}</td>
                  <td>
                    <div className="strong">{t.title}</div>
                    <div className="muted small">{t.client_name || 'Internal'} {t.project_name && `· ${t.project_name}`}</div>
                  </td>
                  <td>
                    <SeverityBadge s={t.severity} />
                  </td>
                  <td>
                    <StatusBadge value={t.status} labelText={t.status_label} /> {t.reopen_count > 0 && <Badge tone="outline">Reopened</Badge>}
                  </td>
                  <td>
                    <Person m={t.owner} />
                  </td>
                  <td className="small">{t.waiting_reason ? `Waiting: ${t.waiting_reason}` : t.next_action || '—'}</td>
                  <td className="muted">{relative(t.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {list.data && <Pager page={page} count={list.data.count} onPage={setPage} />}
      </div>
      {creating && (
        <FormModal
          title="New ticket"
          fields={[
            { name: 'title', label: 'Title', required: true },
            { name: 'description', label: 'Description', type: 'textarea' },
            { name: 'kind', label: 'Type', type: 'select', options: [{ value: 'client', label: 'Client request' }, { value: 'internal', label: 'Internal issue' }], half: true, required: true },
            { name: 'severity', label: 'Severity', type: 'select', options: SEVERITIES, half: true, required: true },
            { name: 'client_id', label: 'Client', type: 'select', options: (clients.data?.results || []).map((c: any) => ({ value: c.id, label: c.name })), half: true, show: (v) => v.kind === 'client' },
            { name: 'project_id', label: 'Project', type: 'select', options: (projects.data?.results || []).map((p: any) => ({ value: p.id, label: `${p.name} (${p.client_name})` })), half: true },
            { name: 'owner_id', label: 'Owner', type: 'member' },
            { name: 'next_action', label: 'Next action' },
          ]}
          initial={{ kind: 'client', severity: 'medium' }}
          onClose={() => setCreating(false)}
          onSubmit={(v) =>
            post('/tickets', v).then((t) => {
              toast(t.severity === 'critical' ? 'Critical ticket created - incident owners notified' : 'Ticket created')
              qc.invalidateQueries({ queryKey: ['tickets'] })
              nav(`/tickets/${t.id}`)
            })
          }
        />
      )}
    </>
  )
}

const NEXT: Record<string, { to: string; label: string; primary?: boolean }[]> = {
  new: [{ to: 'triaged', label: 'Triage', primary: true }, { to: 'in_progress', label: 'Start work' }],
  triaged: [{ to: 'in_progress', label: 'Start work', primary: true }, { to: 'waiting_customer', label: 'Waiting on customer' }, { to: 'waiting_internal', label: 'Waiting internal' }, { to: 'resolved', label: 'Resolve' }],
  in_progress: [{ to: 'resolved', label: 'Resolve', primary: true }, { to: 'waiting_customer', label: 'Waiting on customer' }, { to: 'waiting_internal', label: 'Waiting internal' }],
  waiting_customer: [{ to: 'in_progress', label: 'Resume', primary: true }, { to: 'resolved', label: 'Resolve' }],
  waiting_internal: [{ to: 'in_progress', label: 'Resume', primary: true }, { to: 'resolved', label: 'Resolve' }],
  resolved: [{ to: 'closed', label: 'Close', primary: true }, { to: 'triaged', label: 'Reopen' }],
  closed: [{ to: 'triaged', label: 'Reopen' }],
}

function transitionFields(from: string, to: string, hasOwner: boolean): FieldDef[] {
  const f: FieldDef[] = []
  if (!hasOwner) f.push({ name: 'owner_id', label: 'Owner', type: 'member', required: true })
  if (to.startsWith('waiting'))
    f.push(
      { name: 'waiting_reason', label: 'Waiting for what?', required: true },
      { name: 'waiting_next_owner_id', label: 'Who acts next?', type: 'member', required: true, half: true },
      { name: 'waiting_review_at', label: 'Review on', type: 'datetime', required: true, half: true },
    )
  if (to === 'resolved')
    f.push(
      { name: 'resolution_note', label: 'Resolution - what was done?', type: 'textarea', required: true },
      { name: 'closure_test_result', label: 'Closure test result - how was the fix verified?', type: 'textarea', required: true },
    )
  if (to === 'triaged' && (from === 'resolved' || from === 'closed')) f.push({ name: 'note', label: 'Why is it being reopened?', type: 'textarea', required: true })
  return f
}

export function TicketDetailPage() {
  const { id } = useParams()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['ticket', id], queryFn: () => get<any>(`/tickets/${id}`) })
  const [dialog, setDialog] = useState<{ to?: string; label?: string; kind: string } | null>(null)
  const [note, setNote] = useState('')
  const [visibility, setVisibility] = useState('internal')
  const t = q.data
  if (q.isLoading) return <Spinner />
  if (q.error || !t) return <Empty text={errorText(q.error) || 'Ticket not found.'} />
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['ticket', id] })
    qc.invalidateQueries({ queryKey: ['tickets'] })
  }
  const go = (to: string, label: string) => {
    const fields = transitionFields(t.status, to, !!t.owner)
    if (fields.length) setDialog({ kind: 'transition', to, label })
    else
      post(`/tickets/${t.id}/status`, { status: to, version: t.version })
        .then(() => {
          toast(label)
          refresh()
        })
        .catch((e) => toast(errorText(e), 'error'))
  }
  const addNote = () =>
    post(`/tickets/${t.id}/notes`, { body: note, visibility })
      .then(() => {
        setNote('')
        refresh()
      })
      .catch((e) => toast(errorText(e), 'error'))

  return (
    <>
      <PageHead
        title={`#${t.number} ${t.title}`}
        sub={
          <span className="flex wrap">
            <SeverityBadge s={t.severity} /> <StatusBadge value={t.status} labelText={t.status_label} />
            {t.client_id && (
              <Link className="link" to={`/clients/${t.client_id}`}>
                {t.client_name}
              </Link>
            )}
            {t.project_id && (
              <Link className="link" to={`/projects/${t.project_id}`}>
                {t.project_name}
              </Link>
            )}
          </span>
        }
        actions={
          <>
            {(NEXT[t.status] || []).map((a) => (
              <button key={a.to + a.label} className={`btn ${a.primary ? 'primary' : ''}`} onClick={() => go(a.to, a.label)}>
                {a.label}
              </button>
            ))}
            <button className="btn ghost" onClick={() => setDialog({ kind: 'edit' })}>
              Edit
            </button>
          </>
        }
      />
      <div className="grid detail">
        <div className="stack">
          <Card title="Details">
            <dl className="kv">
              <dt>Owner</dt>
              <dd>
                <Person m={t.owner} />
              </dd>
              <dt>Type</dt>
              <dd>{t.kind === 'client' ? 'Client request' : 'Internal issue'}</dd>
              <dt>Raised by</dt>
              <dd>
                {t.created_by?.name} · {fmtDateTime(t.created_at)}
              </dd>
              <dt>Next action</dt>
              <dd>{t.next_action || '—'}</dd>
              {t.waiting_reason && (
                <>
                  <dt>Waiting</dt>
                  <dd>
                    {t.waiting_reason}
                    <div className="small muted">
                      Next: {t.waiting_next_owner?.name} · review {fmtDateTime(t.waiting_review_at)}
                    </div>
                  </dd>
                </>
              )}
              {t.resolution_note && (
                <>
                  <dt>Resolution</dt>
                  <dd className="pre">{t.resolution_note}</dd>
                  <dt>Closure test</dt>
                  <dd className="pre">{t.closure_test_result}</dd>
                </>
              )}
              <dt>Reopened</dt>
              <dd>{t.reopen_count}×</dd>
            </dl>
            {t.description && <div className="pre" style={{ marginTop: 12 }}>{t.description}</div>}
          </Card>
          <Card title="History" pad={false}>
            <div className="timeline">
              {t.events.map((e: any) => (
                <div key={e.id} className="tl-item">
                  <div className="tl-body">
                    <div>
                      {e.from_status && `${e.from_status} → `}
                      <b>{e.to_status}</b> {e.note && `· ${e.note}`}
                    </div>
                    {e.snapshot?.resolution_note && <div className="small muted">Resolution then: {e.snapshot.resolution_note}</div>}
                    <div className="tl-meta">
                      {e.actor?.name} · {fmtDateTime(e.created_at)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
        <div className="stack">
          <Card title="Notes" pad={false}>
            <div className="card-body">
              <textarea className="textarea" placeholder="Add a note…" value={note} onChange={(e) => setNote(e.target.value)} />
              <div className="flex" style={{ marginTop: 8 }}>
                <Segmented
                  options={[
                    { value: 'internal', label: <span className="flex"><Lock size={13} /> Internal</span> },
                    { value: 'client', label: <span className="flex"><Users size={13} /> Client-visible</span> },
                  ]}
                  value={visibility}
                  onChange={setVisibility}
                />
                <button className="btn primary right" disabled={!note.trim()} onClick={addNote}>
                  Add note
                </button>
              </div>
            </div>
            <div className="timeline">
              {t.notes.length === 0 && <Empty text="No notes yet." />}
              {t.notes.map((n: any) => (
                <div className="tl-item" key={n.id}>
                  <div className="tl-icon">{n.visibility === 'internal' ? <Lock size={14} /> : <Users size={14} />}</div>
                  <div className="tl-body">
                    <div className="pre">{n.body}</div>
                    <div className="tl-meta">
                      {n.author?.name} · {fmtDateTime(n.created_at)} · <Badge tone={n.visibility === 'internal' ? 'outline' : 'dark'}>{n.visibility === 'internal' ? 'Internal' : 'Client-visible'}</Badge>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
          <TaskList filter={{ ticket: t.id }} linkTo={{ ticket_id: t.id }} />
        </div>
      </div>
      {dialog?.kind === 'transition' && dialog.to && (
        <FormModal
          title={dialog.label}
          fields={transitionFields(t.status, dialog.to, !!t.owner)}
          initial={{ waiting_review_at: inHours(48) }}
          onClose={() => setDialog(null)}
          onSubmit={(v) => post(`/tickets/${t.id}/status`, { ...v, status: dialog.to, version: t.version }).then(refresh)}
        />
      )}
      {dialog?.kind === 'edit' && (
        <FormModal
          title="Edit ticket"
          fields={[
            { name: 'title', label: 'Title', required: true },
            { name: 'description', label: 'Description', type: 'textarea' },
            { name: 'severity', label: 'Severity', type: 'select', options: SEVERITIES, half: true },
            { name: 'owner_id', label: 'Owner', type: 'member', half: true },
            { name: 'next_action', label: 'Next action' },
          ]}
          initial={{ title: t.title, description: t.description, severity: t.severity, owner_id: t.owner?.id || '', next_action: t.next_action }}
          onClose={() => setDialog(null)}
          onSubmit={(v) => patch(`/tickets/${t.id}`, { ...v, version: t.version }).then(refresh)}
        />
      )}
    </>
  )
}
