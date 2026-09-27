import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { get, Paged, patch, post, qs } from '../lib/api'
import { useMe } from '../lib/auth'
import { fmtDate, fmtDateTime } from '../lib/format'
import { Badge, Card, Empty, errorText, FieldDef, FormModal, PageHead, Person, Segmented, Spinner, StatusBadge, useToast } from '../components/ui'
import { TaskList } from '../components/work'

export function ProjectsPage() {
  const me = useMe()
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const [filter, setFilter] = useState('active')
  const [creating, setCreating] = useState(false)
  const status = filter === 'active' ? 'pending_handover,accepted,in_progress,ready' : filter === 'done' ? 'completed' : ''
  const q = useQuery({ queryKey: ['projects', filter], queryFn: () => get<Paged<any>>('/projects' + qs({ status, page_size: 200 })) })
  const clients = useQuery({ queryKey: ['clients-all'], queryFn: () => get<Paged<any>>('/clients?page_size=500'), enabled: creating })
  const templates = useQuery({ queryKey: ['templates'], queryFn: () => get<any[]>('/templates'), enabled: creating })
  return (
    <>
      <PageHead
        title="Projects"
        sub="Milestones, owners and acceptance evidence for every client commitment."
        actions={
          me.capabilities.delivery_manage && (
            <button className="btn primary" onClick={() => setCreating(true)}>
              <Plus size={16} /> Project
            </button>
          )
        }
      />
      <div className="toolbar">
        <Segmented options={[{ value: 'active', label: 'Active' }, { value: 'done', label: 'Completed' }, { value: 'all', label: 'All' }]} value={filter} onChange={setFilter} />
      </div>
      {q.isLoading ? (
        <Spinner />
      ) : !q.data?.results.length ? (
        <div className="card">
          <Empty text="No projects here yet. Projects are created when a deal is won." />
        </div>
      ) : (
        <div className="grid two">
          {q.data.results.map((p) => (
            <div key={p.id} className="card" style={{ cursor: 'pointer' }} onClick={() => nav(`/projects/${p.id}`)}>
              <div className="card-head">
                <h3>{p.name}</h3>
                <div className="actions">
                  <StatusBadge value={p.status} labelText={p.status_label} />
                </div>
              </div>
              <div className="card-body stack">
                <div className="flex between">
                  <span className="muted">{p.client_name}</span>
                  <span className="small">
                    {p.progress.accepted}/{p.progress.total} milestones accepted
                  </span>
                </div>
                <div className="progress">
                  <div style={{ width: `${p.progress.percent}%` }} />
                </div>
                <div className="flex between small">
                  <Person m={p.manager} />
                  <span>
                    {p.blocked_count > 0 && <Badge tone="warn">{p.blocked_count} blocked</Badge>} Due {fmtDate(p.due_date)}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {creating && (
        <FormModal
          title="New project"
          fields={[
            { name: 'client_id', label: 'Client', type: 'select', required: true, options: (clients.data?.results || []).map((c: any) => ({ value: c.id, label: c.name })) },
            { name: 'name', label: 'Project name', required: true },
            { name: 'template_id', label: 'Milestone template', type: 'select', options: (templates.data || []).map((t: any) => ({ value: t.id, label: t.name })) },
            { name: 'manager_id', label: 'Project manager', type: 'member', roles: ['delivery_manager', 'delivery_employee', 'owner'] },
          ]}
          initial={{ manager_id: me.membership.id }}
          onClose={() => setCreating(false)}
          onSubmit={(v) =>
            post('/projects', v).then((p) => {
              toast('Project created')
              qc.invalidateQueries({ queryKey: ['projects'] })
              nav(`/projects/${p.id}`)
            })
          }
        />
      )}
    </>
  )
}

type Action = { to: string; label: string; primary?: boolean; fields?: FieldDef[] }

function milestoneActions(ms: any, isReviewer: boolean, meId: string, members: any[]): Action[] {
  const blockFields: FieldDef[] = [
    { name: 'blocker_description', label: 'What is blocking it?', type: 'textarea', required: true },
    { name: 'blocker_next_owner_id', label: 'Who must act next?', type: 'member', required: true },
  ]
  void members
  switch (ms.status) {
    case 'planned':
      return [{ to: 'in_progress', label: 'Start', primary: true }, { to: 'ready', label: 'Mark ready' }]
    case 'ready':
      return [{ to: 'in_progress', label: 'Start', primary: true }, { to: 'blocked', label: 'Blocked', fields: blockFields }]
    case 'in_progress':
      return [
        { to: 'in_review', label: 'Submit for review', primary: true, fields: [{ name: 'evidence', label: 'Evidence for the reviewer (link or description)', type: 'textarea', required: true }] },
        { to: 'blocked', label: 'Blocked', fields: blockFields },
      ]
    case 'blocked':
      return [{ to: 'in_progress', label: 'Unblock', primary: true, fields: [{ name: 'note', label: 'How was it unblocked?' }] }]
    case 'in_review':
      return isReviewer && ms.submitted_by?.id !== meId
        ? [
            { to: 'accepted', label: 'Accept', primary: true, fields: ms.depends_on.some((d: any) => !['accepted', 'cancelled'].includes(d.status)) ? [{ name: 'override_reason', label: 'Predecessors are not accepted. Override reason (managers only)', type: 'textarea', required: true }] : [] },
            { to: 'in_progress', label: 'Request changes', fields: [{ name: 'note', label: 'What needs to change?', type: 'textarea', required: true }] },
          ]
        : isReviewer
          ? [{ to: 'accepted', label: 'Accept (as project manager)', primary: true, fields: ms.depends_on.some((d: any) => !['accepted', 'cancelled'].includes(d.status)) ? [{ name: 'override_reason', label: 'Override reason', type: 'textarea', required: true }] : [] }]
          : []
    case 'accepted':
      return isReviewer ? [{ to: 'in_progress', label: 'Reopen', fields: [{ name: 'note', label: 'Why is it being reopened?', type: 'textarea', required: true }] }] : []
    default:
      return []
  }
}

export function ProjectDetailPage() {
  const { id } = useParams()
  const me = useMe()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['project', id], queryFn: () => get<any>(`/projects/${id}`) })
  const [dialog, setDialog] = useState<{ kind: string; ms?: any; action?: Action; change?: any } | null>(null)
  const p = q.data
  if (q.isLoading) return <Spinner />
  if (q.error || !p) return <Empty text={errorText(q.error) || 'Project not found.'} />
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['project', id] })
    qc.invalidateQueries({ queryKey: ['projects'] })
  }
  const isReviewer = me.capabilities.delivery_manage || p.manager?.id === me.membership.id
  const quick = (ms: any, action: Action) => {
    if (action.fields && action.fields.length) {
      setDialog({ kind: 'transition', ms, action })
      return
    }
    post(`/milestones/${ms.id}`, { status: action.to, version: ms.version })
      .then(() => {
        toast(`${ms.title}: ${action.label}`)
        refresh()
      })
      .catch((e) => toast(errorText(e), 'error'))
  }

  return (
    <>
      <PageHead
        title={p.name}
        sub={
          <span className="flex">
            <Link className="link" to={`/clients/${p.client_id}`}>
              {p.client_name}
            </Link>
            <StatusBadge value={p.status} labelText={p.status_label} />
          </span>
        }
        actions={
          <>
            {isReviewer && (
              <button className="btn" onClick={() => setDialog({ kind: 'milestone' })}>
                <Plus size={15} /> Milestone
              </button>
            )}
            <button className="btn" onClick={() => setDialog({ kind: 'change' })}>
              Scope change / defect
            </button>
            {isReviewer && p.status === 'ready' && (
              <button className="btn primary" onClick={() => setDialog({ kind: 'complete' })}>
                Complete project
              </button>
            )}
          </>
        }
      />
      {p.status === 'pending_handover' && (
        <div className="notice dark" style={{ marginBottom: 14 }}>
          Waiting for the delivery owner to accept the handover. <Link className="link" to={`/handovers?focus=${p.handover_id}`}>Review handover</Link>
        </div>
      )}
      <div className="grid side">
        <div className="stack">
          <Card title={`Milestones (${p.progress.accepted}/${p.progress.total} accepted)`} pad={false}>
            <div style={{ padding: '10px 16px 0' }}>
              <div className="progress">
                <div style={{ width: `${p.progress.percent}%` }} />
              </div>
            </div>
            {p.milestones.length === 0 && <Empty text="No milestones yet." />}
            {p.milestones.map((ms: any) => (
              <div key={ms.id} className="task" style={{ alignItems: 'flex-start' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="flex wrap">
                    <span className="ttl">{ms.title}</span>
                    <StatusBadge value={ms.status} labelText={ms.status_label} />
                    {ms.overdue && <Badge tone="danger">Overdue</Badge>}
                    {ms.reopen_count > 0 && <Badge tone="outline">Reopened {ms.reopen_count}×</Badge>}
                  </div>
                  <div className="meta">
                    <Person m={ms.owner} /> <span>Due {fmtDate(ms.due_date)}</span>
                    {ms.depends_on.length > 0 && <span>After: {ms.depends_on.map((d: any) => `${d.title} (${d.status})`).join(', ')}</span>}
                  </div>
                  {ms.status === 'blocked' && (
                    <div className="notice" style={{ marginTop: 6 }}>
                      Blocked: {ms.blocker_description} · next: {ms.blocker_next_owner?.name}
                    </div>
                  )}
                  {ms.evidence && (
                    <div className="small" style={{ marginTop: 6 }}>
                      <span className="muted">Evidence:</span> {ms.evidence} {ms.submitted_by && <span className="muted">(submitted by {ms.submitted_by.name})</span>}
                    </div>
                  )}
                  {ms.accepted_by && (
                    <div className="small muted">
                      Accepted by {ms.accepted_by.name} {fmtDateTime(ms.accepted_at)} {ms.override_reason && `· override: ${ms.override_reason}`}
                    </div>
                  )}
                  {ms.events.length > 0 && (
                    <details className="small muted" style={{ marginTop: 4 }}>
                      <summary>History ({ms.events.length})</summary>
                      {ms.events.map((e: any) => (
                        <div key={e.id} className="source">
                          {fmtDateTime(e.created_at)} · {e.actor?.name}: {e.from_status} → {e.to_status} {e.note && `· ${e.note}`}
                          {e.evidence_snapshot && <div>Evidence then: {e.evidence_snapshot}</div>}
                        </div>
                      ))}
                    </details>
                  )}
                </div>
                <div className="acts">
                  {p.status !== 'pending_handover' &&
                    milestoneActions(ms, isReviewer, me.membership.id, []).map((a) => (
                      <button key={a.to + a.label} className={`btn sm ${a.primary ? 'primary' : ''}`} onClick={() => quick(ms, a)}>
                        {a.label}
                      </button>
                    ))}
                  {isReviewer && !['accepted', 'cancelled'].includes(ms.status) && (
                    <>
                      <button className="btn sm ghost" onClick={() => setDialog({ kind: 'edit', ms })}>
                        Edit
                      </button>
                      <button
                        className="btn sm ghost"
                        onClick={() =>
                          setDialog({
                            kind: 'transition',
                            ms,
                            action: {
                              to: 'cancelled',
                              label: 'Cancel milestone',
                              fields: [
                                { name: 'cancel_reason', label: 'Reason', required: true },
                                { name: 'cancel_impact', label: 'Impact on the client commitment', type: 'textarea', required: true },
                              ],
                            },
                          })
                        }
                      >
                        Cancel
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </Card>
          <TaskList filter={{ project: p.id }} linkTo={{ project_id: p.id }} title="Project tasks" />
          <Card title="Scope changes and defects" pad={false}>
            {p.changes.length === 0 && <Empty text="None recorded." />}
            {p.changes.map((c: any) => (
              <div key={c.id} className="task">
                <div style={{ flex: 1 }}>
                  <div className="flex">
                    <Badge tone={c.kind === 'defect' ? 'warn' : 'outline'}>{c.kind === 'defect' ? 'Defect' : 'Scope change'}</Badge>
                    <span className="ttl">{c.title}</span>
                    <StatusBadge value={c.status} />
                  </div>
                  {c.description && <div className="small pre" style={{ marginTop: 4 }}>{c.description}</div>}
                  <div className="meta">
                    Raised by {c.raised_by?.name} · {fmtDate(c.created_at)} {c.decision_note && `· ${c.decision_note}`}
                  </div>
                </div>
                {isReviewer && c.status === 'open' && (
                  <div className="acts">
                    {c.kind === 'scope_change' ? (
                      <button className="btn sm" onClick={() => setDialog({ kind: 'decide', change: c })}>
                        Decide
                      </button>
                    ) : (
                      <button className="btn sm" onClick={() => setDialog({ kind: 'decide', change: c })}>
                        Close
                      </button>
                    )}
                  </div>
                )}
              </div>
            ))}
          </Card>
        </div>
        <div className="stack">
          <Card title="Project">
            <dl className="kv">
              <dt>Manager</dt>
              <dd>
                <Person m={p.manager} />
              </dd>
              <dt>Team</dt>
              <dd>{p.members.map((m: any) => m?.name).join(', ') || '—'}</dd>
              <dt>Start</dt>
              <dd>{fmtDate(p.start_date)}</dd>
              <dt>Due</dt>
              <dd>{fmtDate(p.due_date)}</dd>
              <dt>Type</dt>
              <dd>{p.kind}</dd>
            </dl>
            {isReviewer && (
              <button className="btn sm" style={{ marginTop: 10 }} onClick={() => setDialog({ kind: 'project' })}>
                Edit project
              </button>
            )}
          </Card>
          {p.handover && (
            <Card title="What sales promised">
              <div className="pre">{p.handover.scope}</div>
              {p.handover.exclusions && <div className="small muted pre" style={{ marginTop: 6 }}>Excludes: {p.handover.exclusions}</div>}
              <div className="small muted" style={{ marginTop: 6 }}>
                Ref {p.handover.commercial_reference} · promised {fmtDate(p.handover.promised_end)}
              </div>
            </Card>
          )}
          <Card title={`Tickets (${p.tickets.length})`} pad={false}>
            {p.tickets.length ? (
              p.tickets.map((t: any) => (
                <Link key={t.id} to={`/tickets/${t.id}`} className="task" style={{ display: 'flex' }}>
                  <div style={{ flex: 1 }}>
                    <div className="ttl">
                      #{t.number} {t.title}
                    </div>
                    <div className="meta">{t.severity}</div>
                  </div>
                  <StatusBadge value={t.status} labelText={t.status_label} />
                </Link>
              ))
            ) : (
              <Empty text="No tickets." />
            )}
          </Card>
        </div>
      </div>

      {dialog?.kind === 'transition' && dialog.action && (
        <FormModal
          title={`${dialog.ms.title}: ${dialog.action.label}`}
          fields={dialog.action.fields || []}
          onClose={() => setDialog(null)}
          onSubmit={(v) => post(`/milestones/${dialog.ms.id}`, { ...v, status: dialog.action!.to, version: dialog.ms.version }).then(refresh)}
        />
      )}
      {(dialog?.kind === 'milestone' || dialog?.kind === 'edit') && (
        <FormModal
          title={dialog.kind === 'edit' ? 'Edit milestone' : 'New milestone'}
          fields={[
            { name: 'title', label: 'Title', required: true },
            { name: 'description', label: 'Description', type: 'textarea' },
            { name: 'owner_id', label: 'Owner', type: 'member', half: true },
            { name: 'due_date', label: 'Due', type: 'date', half: true },
            {
              name: 'depends_on',
              label: 'Depends on',
              type: 'select',
              options: p.milestones.filter((m: any) => m.id !== dialog.ms?.id).map((m: any) => ({ value: m.id, label: m.title })),
              hint: 'Accepting this milestone will wait for the one you pick.',
            },
          ]}
          initial={dialog.ms ? { title: dialog.ms.title, description: dialog.ms.description, owner_id: dialog.ms.owner?.id || '', due_date: dialog.ms.due_date || '', depends_on: dialog.ms.depends_on[0]?.id || '' } : {}}
          onClose={() => setDialog(null)}
          onSubmit={(v) => {
            const body = { ...v, depends_on: v.depends_on ? [v.depends_on] : [] }
            return (dialog.kind === 'edit' ? patch(`/milestones/${dialog.ms.id}`, { ...body, version: dialog.ms.version }) : post(`/projects/${p.id}/milestones`, body)).then(refresh)
          }}
        />
      )}
      {dialog?.kind === 'change' && (
        <FormModal
          title="Record scope change or defect"
          intro="Scope changes (new requests) are tracked separately from defects (something promised that does not work)."
          fields={[
            { name: 'kind', label: 'Type', type: 'select', required: true, options: [{ value: 'scope_change', label: 'Scope change' }, { value: 'defect', label: 'Defect' }] },
            { name: 'title', label: 'Title', required: true },
            { name: 'description', label: 'Details', type: 'textarea' },
          ]}
          onClose={() => setDialog(null)}
          onSubmit={(v) => post(`/projects/${p.id}/changes`, v).then(refresh)}
        />
      )}
      {dialog?.kind === 'decide' && (
        <FormModal
          title={dialog.change.title}
          fields={[
            {
              name: 'status',
              label: 'Decision',
              type: 'select',
              required: true,
              options:
                dialog.change.kind === 'scope_change'
                  ? [{ value: 'approved', label: 'Approve' }, { value: 'rejected', label: 'Reject' }]
                  : [{ value: 'fixed', label: 'Fixed' }, { value: 'rejected', label: 'Not a defect' }],
            },
            { name: 'note', label: 'Note' },
          ]}
          onClose={() => setDialog(null)}
          onSubmit={(v) => post(`/project-changes/${dialog.change.id}`, v).then(refresh)}
        />
      )}
      {dialog?.kind === 'complete' && (
        <FormModal
          title="Complete project"
          fields={[
            { name: 'completion_checklist', label: 'Completion checklist (handover docs, access returned, client sign-off…)', type: 'textarea', required: true },
            { name: 'accept_open_tickets', label: 'Open tickets', type: 'checkbox', hint: 'Complete even though tickets are still open' },
          ]}
          onClose={() => setDialog(null)}
          onSubmit={(v) => post(`/projects/${p.id}/complete`, { ...v, version: p.version }).then(refresh)}
        />
      )}
      {dialog?.kind === 'project' && (
        <FormModal
          title="Edit project"
          fields={[
            { name: 'name', label: 'Name', required: true },
            { name: 'manager_id', label: 'Manager', type: 'member', roles: ['delivery_manager', 'delivery_employee', 'owner'] },
            { name: 'member_ids', label: 'Team members', type: 'multimember' },
            { name: 'start_date', label: 'Start', type: 'date', half: true },
            { name: 'due_date', label: 'Due', type: 'date', half: true },
          ]}
          initial={{ name: p.name, manager_id: p.manager?.id || '', member_ids: p.members.map((m: any) => m.id), start_date: p.start_date || '', due_date: p.due_date || '' }}
          onClose={() => setDialog(null)}
          onSubmit={(v) => patch(`/projects/${p.id}`, { ...v, version: p.version }).then(refresh)}
        />
      )}
    </>
  )
}
