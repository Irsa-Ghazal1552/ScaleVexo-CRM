import { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { get, Paged, post, qs } from '../lib/api'
import { useMe } from '../lib/auth'
import { CURRENCIES, fmtDate, money } from '../lib/format'
import { Card, Empty, errorText, FormModal, PageHead, Pager, Person, Segmented, Spinner, StatusBadge, useToast } from '../components/ui'
import { AIPanel, TaskList, Timeline } from '../components/work'

export function ClientsPage() {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const [q, setQ] = useState(params.get('q') || '')
  const [page, setPage] = useState(1)
  const list = useQuery({ queryKey: ['clients', q, page], queryFn: () => get<Paged<any>>('/clients' + qs({ q, page })) })
  return (
    <>
      <PageHead title="Clients" sub="Created automatically when a deal is won. The same contact carries over - nobody re-types it." />
      <div className="toolbar">
        <input className="input grow" placeholder="Search clients…" defaultValue={q} onKeyDown={(e) => e.key === 'Enter' && setQ((e.target as HTMLInputElement).value)} />
      </div>
      <div className="table-wrap">
        {list.isLoading ? (
          <Spinner />
        ) : !list.data?.results.length ? (
          <Empty text="No clients yet. Win a deal to create one." />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Client</th>
                <th>Primary contact</th>
                <th>Account owner</th>
                <th>Delivery manager</th>
                <th>Projects</th>
                <th>Open tickets</th>
                <th>Since</th>
              </tr>
            </thead>
            <tbody>
              {list.data.results.map((c) => (
                <tr key={c.id} className="click" onClick={() => nav(`/clients/${c.id}`)}>
                  <td className="strong">{c.name}</td>
                  <td>
                    {c.primary_contact.name}
                    <div className="muted small">{c.primary_contact.email}</div>
                  </td>
                  <td>
                    <Person m={c.account_owner} />
                  </td>
                  <td>
                    <Person m={c.delivery_manager} />
                  </td>
                  <td>{c.project_count}</td>
                  <td>{c.open_ticket_count}</td>
                  <td className="muted">{fmtDate(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {list.data && <Pager page={page} count={list.data.count} onPage={setPage} />}
      </div>
    </>
  )
}

export function ClientDetailPage() {
  const { id } = useParams()
  const me = useMe()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['client', id], queryFn: () => get<any>(`/clients/${id}`) })
  const [dialog, setDialog] = useState<string | null>(null)
  const c = q.data
  if (q.isLoading) return <Spinner />
  if (q.error || !c) return <Empty text={errorText(q.error) || 'Client not found.'} />
  const refresh = () => qc.invalidateQueries({ queryKey: ['client', id] })
  const contact = c.primary_contact
  return (
    <>
      <PageHead
        title={c.name}
        sub={<StatusBadge value={c.status} />}
        actions={
          <>
            <button className="btn" onClick={() => setDialog('ticket')}>
              <Plus size={15} /> Ticket
            </button>
            {me.capabilities.receipts && (
              <button className="btn" onClick={() => setDialog('receipt')}>
                Record receipt
              </button>
            )}
          </>
        }
      />
      <div className="grid detail">
        <div className="stack">
          <Card title="Client">
            <dl className="kv">
              <dt>Contact</dt>
              <dd>
                {contact.name}
                <div className="muted small">{contact.title}</div>
              </dd>
              <dt>Email</dt>
              <dd>{contact.email || '—'}</dd>
              <dt>Phone</dt>
              <dd>{contact.phone || '—'}</dd>
              <dt>Account owner</dt>
              <dd>
                <Person m={c.account_owner} />
              </dd>
              <dt>Delivery manager</dt>
              <dd>
                <Person m={c.delivery_manager} />
              </dd>
            </dl>
          </Card>
          <Card title="Accepted scope">
            {c.handovers.length ? (
              c.handovers.map((h: any) => (
                <div key={h.id} className="stack" style={{ marginBottom: 12 }}>
                  <div className="flex">
                    <b>{h.opportunity.title}</b>
                    <StatusBadge value={h.status} labelText={h.status_label} />
                  </div>
                  <div className="pre">{h.scope}</div>
                  {h.exclusions && <div className="small muted pre">Excludes: {h.exclusions}</div>}
                  <div className="small muted">
                    Ref: {h.commercial_reference} · promised {fmtDate(h.promised_start)} → {fmtDate(h.promised_end)}
                  </div>
                </div>
              ))
            ) : (
              <Empty text="No handovers." />
            )}
          </Card>
          <Card title={`Projects (${c.projects.length})`} pad={false}>
            {c.projects.length ? (
              c.projects.map((p: any) => (
                <Link key={p.id} to={`/projects/${p.id}`} className="task" style={{ display: 'flex' }}>
                  <div style={{ flex: 1 }}>
                    <div className="ttl">{p.name}</div>
                    <div className="progress" style={{ marginTop: 6 }}>
                      <div style={{ width: `${p.progress.percent}%` }} />
                    </div>
                  </div>
                  <StatusBadge value={p.status} labelText={p.status_label} />
                </Link>
              ))
            ) : (
              <Empty text="No projects." />
            )}
          </Card>
          <Card title={`Tickets (${c.tickets.length})`} pad={false}>
            {c.tickets.length ? (
              c.tickets.map((t: any) => (
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
          <Card title="Sales history" pad={false}>
            {c.opportunities.length ? (
              c.opportunities.map((o: any) => (
                <div key={o.id} className="task">
                  <div style={{ flex: 1 }}>
                    {me.capabilities.sales ? (
                      <Link className="ttl link" to={`/deals/${o.id}`}>
                        {o.title}
                      </Link>
                    ) : (
                      <div className="ttl">{o.title}</div>
                    )}
                    <div className="meta">
                      {o.value !== null && money(o.value, o.currency)} · owner {o.owner?.name}
                    </div>
                  </div>
                  <StatusBadge value={o.stage} labelText={o.stage_label} />
                </div>
              ))
            ) : (
              <Empty text="No sales history." />
            )}
          </Card>
          {c.receipts && (
            <Card title="Cash receipts" pad={false}>
              {c.receipts.length ? (
                c.receipts.map((r: any) => (
                  <div key={r.id} className="task">
                    <div style={{ flex: 1 }}>
                      <div className="ttl">{money(r.amount, r.currency)}</div>
                      <div className="meta">
                        {fmtDate(r.received_on)} · {r.evidence_reference}
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <Empty text="No receipts recorded." />
              )}
            </Card>
          )}
        </div>
        <div className="stack">
          <AIPanel entityType="client" entityId={c.id} allowDraft={me.capabilities.sales || me.capabilities.delivery_manage} />
          <TaskList filter={{ client: c.id }} linkTo={{ client_id: c.id }} />
          <Timeline target={{ client_id: c.id }} />
        </div>
      </div>
      {dialog === 'ticket' && (
        <FormModal
          title="New ticket"
          fields={[
            { name: 'title', label: 'Title', required: true },
            { name: 'description', label: 'Description', type: 'textarea' },
            { name: 'project_id', label: 'Project', type: 'select', options: c.projects.map((p: any) => ({ value: p.id, label: p.name })) },
            { name: 'severity', label: 'Severity', type: 'select', options: ['low', 'medium', 'high', 'critical'].map((s) => ({ value: s, label: s })), half: true, required: true },
            { name: 'owner_id', label: 'Owner', type: 'member', half: true },
          ]}
          initial={{ severity: 'medium' }}
          onClose={() => setDialog(null)}
          onSubmit={(v) => post('/tickets', { ...v, client_id: c.id }).then(() => { toast('Ticket created'); refresh() })}
        />
      )}
      {dialog === 'receipt' && (
        <FormModal
          title="Record cash receipt"
          intro="An operational record of money received - not an accounting ledger."
          fields={[
            { name: 'amount', label: 'Amount', type: 'number', required: true, half: true },
            { name: 'currency', label: 'Currency', type: 'select', options: CURRENCIES.map((x) => ({ value: x, label: x })), required: true, half: true },
            { name: 'received_on', label: 'Date received', type: 'date', required: true, half: true },
            { name: 'opportunity_id', label: 'For deal', type: 'select', options: c.opportunities.map((o: any) => ({ value: o.id, label: o.title })), half: true },
            { name: 'evidence_reference', label: 'Evidence (bank ref, invoice no.)', required: true },
            { name: 'note', label: 'Note' },
          ]}
          initial={{ currency: me.workspace.default_currency, received_on: new Date().toISOString().slice(0, 10) }}
          onClose={() => setDialog(null)}
          onSubmit={(v) => post('/receipts', { ...v, client_id: c.id }).then(() => { toast('Receipt recorded'); refresh() })}
        />
      )}
    </>
  )
}

export function HandoversPage() {
  const me = useMe()
  const qc = useQueryClient()
  const toast = useToast()
  const [params] = useSearchParams()
  const focus = params.get('focus')
  const [status, setStatus] = useState('pending,exception,returned')
  const q = useQuery({ queryKey: ['handovers', status], queryFn: () => get<any[]>('/handovers' + qs({ status })) })
  const [dialog, setDialog] = useState<{ h: any; action: 'return' | 'resubmit' } | null>(null)
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['handovers'] })
    qc.invalidateQueries({ queryKey: ['today'] })
    qc.invalidateQueries({ queryKey: ['alerts-count'] })
  }
  const accept = (h: any) =>
    post(`/handovers/${h.id}/accept`, {})
      .then(() => {
        toast('Handover accepted - delivery can start')
        refresh()
      })
      .catch((e) => toast(errorText(e), 'error'))

  return (
    <>
      <PageHead title="Handovers" sub="Sales → delivery. Delivery accepts the promise, or returns it with what is missing." />
      <div className="toolbar">
        <Segmented
          options={[
            { value: 'pending,exception,returned', label: 'Needs action' },
            { value: 'accepted', label: 'Accepted' },
            { value: '', label: 'All' },
          ]}
          value={status}
          onChange={setStatus}
        />
      </div>
      {q.isLoading ? (
        <Spinner />
      ) : !q.data?.length ? (
        <div className="card">
          <Empty text="No handovers here." />
        </div>
      ) : (
        <div className="grid two">
          {q.data.map((h) => {
            const canDecide = me.capabilities.delivery_manage || h.delivery_owner?.id === me.membership.id
            const canResubmit = me.capabilities.sales_manage || h.opportunity.owner?.id === me.membership.id || me.capabilities.delivery_manage
            return (
              <div key={h.id} className="card" style={focus === h.id ? { borderColor: '#111', borderWidth: 2 } : undefined}>
                <div className="card-head">
                  <h3>{h.client_name}</h3>
                  <div className="actions">
                    <StatusBadge value={h.status} labelText={h.status_label} />
                  </div>
                </div>
                <div className="card-body stack">
                  <div>
                    <b>{h.opportunity.title}</b>
                    {h.opportunity.value && <span className="muted"> · {money(h.opportunity.value, h.opportunity.currency)}</span>}
                  </div>
                  <div>
                    <div className="muted small">Scope</div>
                    <div className="pre">{h.scope}</div>
                  </div>
                  {h.exclusions && (
                    <div>
                      <div className="muted small">Exclusions</div>
                      <div className="pre">{h.exclusions}</div>
                    </div>
                  )}
                  <dl className="kv">
                    <dt>Reference</dt>
                    <dd>{h.commercial_reference}</dd>
                    <dt>Decision</dt>
                    <dd>{h.opportunity.commercial_decision}</dd>
                    <dt>Client contacts</dt>
                    <dd className="pre">{h.client_contacts || '—'}</dd>
                    <dt>Promised</dt>
                    <dd>
                      {fmtDate(h.promised_start)} → {fmtDate(h.promised_end)} {h.promised_dates_note}
                    </dd>
                    <dt>Sales owner</dt>
                    <dd>
                      <Person m={h.opportunity.owner} />
                    </dd>
                    <dt>Delivery owner</dt>
                    <dd>
                      <Person m={h.delivery_owner} />
                    </dd>
                  </dl>
                  {h.return_reason && <div className="notice">Returned: {h.return_reason}</div>}
                  <div className="flex wrap">
                    {h.project_id && (
                      <Link className="btn sm" to={`/projects/${h.project_id}`}>
                        Open project
                      </Link>
                    )}
                    {h.status !== 'accepted' && canDecide && (
                      <>
                        <button className="btn sm primary" onClick={() => accept(h)}>
                          Accept handover
                        </button>
                        {h.status !== 'returned' && (
                          <button className="btn sm" onClick={() => setDialog({ h, action: 'return' })}>
                            Return to sales
                          </button>
                        )}
                      </>
                    )}
                    {h.status !== 'accepted' && canResubmit && (h.status === 'returned' || h.status === 'exception') && (
                      <button className="btn sm" onClick={() => setDialog({ h, action: 'resubmit' })}>
                        Update & resubmit
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
      {dialog?.action === 'return' && (
        <FormModal
          title="Return handover"
          fields={[{ name: 'reason', label: 'What information is missing?', type: 'textarea', required: true }]}
          onClose={() => setDialog(null)}
          onSubmit={(v) => post(`/handovers/${dialog.h.id}/return`, v).then(refresh)}
        />
      )}
      {dialog?.action === 'resubmit' && (
        <FormModal
          title="Update handover"
          wide
          fields={[
            { name: 'scope', label: 'Scope', type: 'textarea', required: true },
            { name: 'exclusions', label: 'Exclusions', type: 'textarea' },
            { name: 'commercial_reference', label: 'Commercial reference', required: true, half: true },
            { name: 'delivery_owner_id', label: 'Delivery owner', type: 'member', roles: ['delivery_manager', 'delivery_employee', 'owner'], half: true },
            { name: 'client_contacts', label: 'Client contacts', type: 'textarea' },
            { name: 'promised_start', label: 'Promised start', type: 'date', half: true },
            { name: 'promised_end', label: 'Promised delivery', type: 'date', half: true },
          ]}
          initial={{
            scope: dialog.h.scope, exclusions: dialog.h.exclusions, commercial_reference: dialog.h.commercial_reference,
            delivery_owner_id: dialog.h.delivery_owner?.id || '', client_contacts: dialog.h.client_contacts,
            promised_start: dialog.h.promised_start || '', promised_end: dialog.h.promised_end || '',
          }}
          onClose={() => setDialog(null)}
          onSubmit={(v) => post(`/handovers/${dialog.h.id}/resubmit`, { ...v, version: dialog.h.version }).then(refresh)}
        />
      )}
    </>
  )
}
