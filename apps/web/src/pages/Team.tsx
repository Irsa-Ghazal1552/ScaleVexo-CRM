import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, UserPlus } from 'lucide-react'
import { get, patch, post } from '../lib/api'
import { useMe } from '../lib/auth'
import { fmtDate, fmtDateTime, relative, ROLE_LABELS } from '../lib/format'
import { Avatar, Badge, Card, Empty, errorText, FormModal, PageHead, Spinner, StatusBadge, Tabs, useToast } from '../components/ui'

export default function TeamPage() {
  const me = useMe()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') || 'members'
  const tabs = [
    { value: 'members', label: 'Members' },
    ...(me.capabilities.configure ? [{ value: 'invitations', label: 'Invitations' }] : []),
    { value: 'accountability', label: me.capabilities.manager ? 'Accountability' : 'My activity record' },
    { value: 'corrections', label: 'Correction requests' },
  ]
  return (
    <>
      <PageHead title="Team" sub={`${me.workspace.name} workspace`} />
      <Tabs tabs={tabs} value={tab} onChange={(v) => setParams({ tab: v })} />
      {tab === 'members' && <Members />}
      {tab === 'invitations' && <Invitations />}
      {tab === 'accountability' && <Accountability />}
      {tab === 'corrections' && <Corrections />}
    </>
  )
}

function Members() {
  const me = useMe()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['members-all'], queryFn: () => get<any[]>('/team/members') })
  const [dialog, setDialog] = useState<{ kind: string; m: any } | null>(null)
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['members-all'] })
    qc.invalidateQueries({ queryKey: ['members'] })
  }
  const canTransfer = me.capabilities.manager || me.capabilities.configure
  if (q.isLoading) return <Spinner />
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Role</th>
            <th>Status</th>
            <th>MFA</th>
            <th>On leave until</th>
            <th>Last sign-in</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(q.data || []).map((m) => (
            <tr key={m.id}>
              <td>
                <div className="flex">
                  <Avatar name={m.name} />
                  <div>
                    <div className="strong">{m.name}</div>
                    <div className="muted small">
                      {m.email} {m.title && `· ${m.title}`}
                    </div>
                  </div>
                </div>
              </td>
              <td>{m.role_label}</td>
              <td>
                <StatusBadge value={m.status} />
              </td>
              <td>{m.mfa_enabled ? <Badge tone="dark">On</Badge> : <span className="muted">Off</span>}</td>
              <td>{m.unavailable_until ? fmtDate(m.unavailable_until) : <span className="muted">—</span>}</td>
              <td className="muted">{m.last_login ? relative(m.last_login) : 'Never'}</td>
              <td>
                <div className="flex" style={{ justifyContent: 'flex-end' }}>
                  {me.capabilities.configure && (
                    <button className="btn sm ghost" onClick={() => setDialog({ kind: 'edit', m })}>
                      Edit
                    </button>
                  )}
                  {canTransfer && m.id !== me.membership.id && (
                    <button className="btn sm ghost" onClick={() => setDialog({ kind: 'transfer', m })}>
                      Transfer work
                    </button>
                  )}
                  {me.capabilities.configure && m.id !== me.membership.id && (m.status === 'active' ? (
                    <button className="btn sm danger" onClick={() => setDialog({ kind: 'suspend', m })}>
                      Suspend
                    </button>
                  ) : (
                    <button className="btn sm" onClick={() => post(`/team/members/${m.id}/reactivate`).then(refresh).catch((e) => toast(errorText(e), 'error'))}>
                      Reactivate
                    </button>
                  ))}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {dialog?.kind === 'edit' && (
        <FormModal
          title={`Edit ${dialog.m.name}`}
          fields={[
            { name: 'first_name', label: 'First name', half: true },
            { name: 'last_name', label: 'Last name', half: true },
            { name: 'role', label: 'Role', type: 'select', options: me.roles, half: true },
            { name: 'title', label: 'Job title', half: true },
            { name: 'unavailable_until', label: 'Approved leave until (no automatic assignments)', type: 'date' },
          ]}
          initial={{ first_name: dialog.m.first_name, last_name: dialog.m.last_name, role: dialog.m.role, title: dialog.m.title, unavailable_until: dialog.m.unavailable_until || '' }}
          onClose={() => setDialog(null)}
          onSubmit={(v) => patch(`/team/members/${dialog.m.id}`, v).then(refresh)}
        />
      )}
      {dialog?.kind === 'suspend' && (
        <FormModal
          title={`Suspend ${dialog.m.name}`}
          intro="Access stops immediately, including open sessions. Their history stays. Transfer their open work afterwards."
          fields={[{ name: 'reason', label: 'Reason', required: true }]}
          submitLabel="Suspend access"
          onClose={() => setDialog(null)}
          onSubmit={(v) => post(`/team/members/${dialog.m.id}/suspend`, v).then(refresh)}
        />
      )}
      {dialog?.kind === 'transfer' && (
        <FormModal
          title={`Transfer open work from ${dialog.m.name}`}
          intro="Open leads, deals, tasks and tickets move to the new owner. Original authors of activities are kept."
          fields={[
            { name: 'to_member', label: 'Transfer to', type: 'member', required: true },
            { name: 'reason', label: 'Reason', required: true },
          ]}
          onClose={() => setDialog(null)}
          onSubmit={(v) =>
            post(`/team/members/${dialog.m.id}/reassign`, v).then((r) => {
              const c = r.transferred
              toast(`Transferred ${c.leads} leads, ${c.opportunities} deals, ${c.tasks} tasks, ${c.tickets} tickets`)
              refresh()
            })
          }
        />
      )}
    </div>
  )
}

function Invitations() {
  const me = useMe()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['invitations'], queryFn: () => get<any[]>('/team/invitations') })
  const [open, setOpen] = useState(false)
  const refresh = () => qc.invalidateQueries({ queryKey: ['invitations'] })
  const copy = (link: string) => {
    navigator.clipboard?.writeText(link)
    toast('Invitation link copied - send it to the person')
  }
  return (
    <Card title="Invitations" actions={<button className="btn sm primary" onClick={() => setOpen(true)}><UserPlus size={14} /> Invite</button>} pad={false}>
      <div className="card-body">
        <div className="notice">Access is invitation-only. Emails are not sent automatically in Release 1 - copy the link and send it yourself. Links expire after 7 days.</div>
      </div>
      {q.isLoading ? (
        <Spinner />
      ) : !q.data?.length ? (
        <Empty text="No invitations yet." />
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Email</th>
              <th>Role</th>
              <th>Status</th>
              <th>Invited</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {q.data.map((i) => (
              <tr key={i.id}>
                <td>{i.email}</td>
                <td>{ROLE_LABELS[i.role]}</td>
                <td>
                  <StatusBadge value={i.status} />
                </td>
                <td className="muted">
                  {fmtDateTime(i.created_at)} by {i.invited_by_name}
                </td>
                <td>
                  {i.status === 'pending' && (
                    <div className="flex" style={{ justifyContent: 'flex-end' }}>
                      <button className="btn sm" onClick={() => copy(i.link)}>
                        <Copy size={13} /> Copy link
                      </button>
                      <button className="btn sm ghost" onClick={() => post(`/team/invitations/${i.id}/revoke`).then(refresh)}>
                        Revoke
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {open && (
        <FormModal
          title="Invite a team member"
          fields={[
            { name: 'email', label: 'Work email', type: 'email', required: true },
            { name: 'role', label: 'Role', type: 'select', options: me.roles, required: true, half: true },
            { name: 'title', label: 'Job title', half: true },
          ]}
          onClose={() => setOpen(false)}
          onSubmit={(v) =>
            post('/team/invitations', v).then((i) => {
              refresh()
              copy(i.link)
            })
          }
        />
      )}
    </Card>
  )
}

function Accountability() {
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const q = useQuery({ queryKey: ['accountability', from, to], queryFn: () => get<any>(`/reports/accountability?from=${from}&to=${to}`) })
  return (
    <div className="stack">
      <div className="toolbar">
        <span className="muted">Period</span>
        <input className="input" type="date" style={{ width: 170 }} value={from} onChange={(e) => setFrom(e.target.value)} />
        <input className="input" type="date" style={{ width: 170 }} value={to} onChange={(e) => setTo(e.target.value)} />
        {q.data && (
          <span className="muted small">
            {q.data.filters.from} → {q.data.filters.to}
          </span>
        )}
      </div>
      {q.data && <div className="notice">{q.data.note}</div>}
      <div className="table-wrap">
        {q.isLoading ? (
          <Spinner />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Person</th>
                <th>Open tasks</th>
                <th>Overdue now</th>
                <th>Missed deadlines</th>
                <th>Completed</th>
                <th>Reschedules</th>
                <th>Self-reported activity</th>
                <th>Provider-confirmed</th>
              </tr>
            </thead>
            <tbody>
              {(q.data?.rows || []).map((r: any) => (
                <tr key={r.member.id}>
                  <td>
                    <div className="strong">{r.member.name}</div>
                    <div className="muted small">{ROLE_LABELS[r.member.role]}</div>
                  </td>
                  <td>{r.open_tasks}</td>
                  <td className={r.overdue_now ? 'overdue' : ''}>{r.overdue_now}</td>
                  <td>{r.missed_deadlines_in_period}</td>
                  <td>{r.completed_in_period}</td>
                  <td>{r.reschedules_in_period}</td>
                  <td>{r.activities_self_reported}</td>
                  <td>{r.activities_provider_confirmed}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

function Corrections() {
  const me = useMe()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['corrections'], queryFn: () => get<any[]>('/corrections') })
  const [deciding, setDeciding] = useState<any>(null)
  const refresh = () => qc.invalidateQueries({ queryKey: ['corrections'] })
  if (q.isLoading) return <Spinner />
  return (
    <Card title="Correction requests" pad={false}>
      <div className="card-body">
        <div className="notice">Employees can see their own records and request corrections. Approved time corrections are applied with a visible correction trail.</div>
      </div>
      {!q.data?.length ? (
        <Empty text="No correction requests." />
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Requested by</th>
              <th>Record</th>
              <th>Change</th>
              <th>Reason</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {q.data.map((c) => (
              <tr key={c.id}>
                <td>
                  {c.requested_by?.name}
                  <div className="muted small">{fmtDateTime(c.created_at)}</div>
                </td>
                <td>
                  {c.entity_type} {c.field && `· ${c.field}`}
                </td>
                <td className="small">
                  {c.current_value && <div className="muted">From: {c.field === 'occurred_at' ? fmtDateTime(c.current_value) : c.current_value}</div>}
                  <div>To: {c.field === 'occurred_at' ? fmtDateTime(c.requested_value) : c.requested_value}</div>
                </td>
                <td>{c.reason}</td>
                <td>
                  <StatusBadge value={c.status} />
                  {c.review_note && <div className="small muted">{c.review_note}</div>}
                </td>
                <td>
                  {me.capabilities.manager && c.status === 'open' && c.requested_by?.id !== me.membership.id && (
                    <button className="btn sm" onClick={() => setDeciding(c)}>
                      Review
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {deciding && (
        <FormModal
          title="Review correction"
          fields={[
            { name: 'status', label: 'Decision', type: 'select', required: true, options: [{ value: 'approved', label: 'Approve and apply' }, { value: 'rejected', label: 'Reject' }] },
            { name: 'note', label: 'Note to the employee' },
          ]}
          onClose={() => setDeciding(null)}
          onSubmit={(v) => post(`/corrections/${deciding.id}`, v).then(refresh)}
        />
      )}
    </Card>
  )
}
