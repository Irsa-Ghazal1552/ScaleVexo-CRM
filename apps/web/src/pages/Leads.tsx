import { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Plus, Upload } from 'lucide-react'
import { ApiError, download, get, Paged, patch, post, qs } from '../lib/api'
import { useMe } from '../lib/auth'
import { CURRENCIES, fmtDate, fmtDateTime, LEAD_STATUSES, label, money, relative, toLocalInput } from '../lib/format'
import { Badge, Card, Empty, errorText, FieldDef, FormModal, PageHead, Pager, Person, Segmented, Spinner, StatusBadge, useToast } from '../components/ui'
import { AIPanel, History, StageBar, TaskList, Timeline } from '../components/work'

const SALES_ROLES = ['owner', 'sales_manager', 'sales_rep']

export function leadFields(isManager: boolean): FieldDef[] {
  return [
    { name: 'name', label: 'Contact name', half: true },
    { name: 'company_name', label: 'Company', half: true },
    { name: 'email', label: 'Email', type: 'email', half: true },
    { name: 'phone', label: 'Phone', half: true, hint: 'Use +country code, e.g. +92 300 1234567' },
    { name: 'linkedin_url', label: 'LinkedIn URL', half: true },
    { name: 'country', label: 'Country (2 letters)', half: true, placeholder: 'PK, US…' },
    { name: 'source', label: 'Source', half: true, placeholder: 'LinkedIn, Referral, Website…' },
    { name: 'source_reference', label: 'Source reference', half: true, placeholder: 'Link or reference' },
    ...(isManager ? [{ name: 'owner_id', label: 'Owner', type: 'member' as const, roles: SALES_ROLES }] : []),
    { name: 'next_action', label: 'Next action', half: true },
    { name: 'next_action_due', label: 'Next action due', type: 'datetime', half: true },
  ]
}

export function LeadsPage() {
  const me = useMe()
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const [page, setPage] = useState(1)
  const [creating, setCreating] = useState(false)
  const [dupe, setDupe] = useState<string>('')
  const q = params.get('q') || ''
  const status = params.get('status') || ''
  const owner = params.get('owner') || (me.capabilities.sales_manage ? '' : 'me')
  const list = useQuery({
    queryKey: ['leads', q, status, owner, page],
    queryFn: () => get<Paged<any>>('/leads' + qs({ q, status, owner, page })),
  })
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params)
    if (v) next.set(k, v)
    else next.delete(k)
    setParams(next)
    setPage(1)
  }

  return (
    <>
      <PageHead
        title="Leads"
        sub="People and companies we are contacting. A lead becomes one or more deals."
        actions={
          <>
            {me.capabilities.sales_manage && (
              <>
                <Link to="/settings?tab=import" className="btn">
                  <Upload size={15} /> Import CSV
                </Link>
                <button className="btn" onClick={() => download('/export/leads.csv', 'leads.csv').catch((e) => toast(errorText(e), 'error'))}>
                  <Download size={15} /> Export
                </button>
              </>
            )}
            <button className="btn primary" onClick={() => setCreating(true)}>
              <Plus size={16} /> Lead
            </button>
          </>
        }
      />
      <div className="toolbar">
        <input className="input grow" placeholder="Search name, company, email, phone, source…" defaultValue={q} onKeyDown={(e) => e.key === 'Enter' && set('q', (e.target as HTMLInputElement).value)} />
        <select className="select" style={{ width: 170 }} value={status} onChange={(e) => set('status', e.target.value)} aria-label="Status">
          <option value="">All statuses</option>
          {LEAD_STATUSES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        {me.capabilities.sales_manage && (
          <Segmented
            options={[
              { value: '', label: 'All' },
              { value: 'me', label: 'Mine' },
              { value: 'none', label: 'Unassigned' },
            ]}
            value={owner}
            onChange={(v) => set('owner', v)}
          />
        )}
      </div>
      <div className="table-wrap">
        {list.isLoading ? (
          <Spinner />
        ) : !list.data?.results.length ? (
          <Empty text={q || status ? 'No leads match these filters.' : 'No leads yet. Add one or import your spreadsheet.'} />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Lead</th>
                <th>Status</th>
                <th>Owner</th>
                <th>Source</th>
                <th>Next action</th>
                <th>Last activity</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {list.data.results.map((l) => (
                <tr key={l.id} className="click" onClick={() => nav(`/leads/${l.id}`)}>
                  <td>
                    <div className="strong">{l.contact.name || l.contact.company_name}</div>
                    <div className="muted small">{l.contact.name ? l.contact.company_name : l.contact.email}</div>
                  </td>
                  <td>
                    <StatusBadge value={l.status} labelText={l.status_label} />
                  </td>
                  <td>
                    <Person m={l.owner} />
                  </td>
                  <td>{l.source || <span className="muted">—</span>}</td>
                  <td>
                    {l.next_action ? (
                      <>
                        <div>{l.next_action}</div>
                        <div className={`small ${l.next_action_overdue ? 'overdue' : 'muted'}`}>{fmtDateTime(l.next_action_due)}</div>
                      </>
                    ) : (
                      <span className="muted">None</span>
                    )}
                  </td>
                  <td className="muted">{relative(l.last_activity_at)}</td>
                  <td className="muted">{fmtDate(l.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {list.data && <Pager page={page} count={list.data.count} onPage={setPage} />}
      </div>
      {creating && (
        <FormModal
          title="New lead"
          wide
          intro={dupe || 'Only a name or company, one contact method (or source reference) and an owner are needed now.'}
          fields={leadFields(me.capabilities.sales_manage)}
          initial={{ owner_id: me.membership.role === 'sales_rep' ? me.membership.id : '' }}
          onClose={() => {
            setCreating(false)
            setDupe('')
          }}
          onSubmit={async (v) => {
            try {
              const lead = await post('/leads', v)
              qc.invalidateQueries({ queryKey: ['leads'] })
              toast('Lead created')
              nav(`/leads/${lead.id}`)
            } catch (e) {
              if (e instanceof ApiError && e.code === 'duplicate_contact') setDupe(e.message)
              throw e
            }
          }}
        />
      )}
    </>
  )
}

const LEAD_FLOW = LEAD_STATUSES.filter((s) => !['nurture', 'disqualified'].includes(s.value))

export function LeadDetailPage() {
  const { id } = useParams()
  const me = useMe()
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['lead', id], queryFn: () => get<any>(`/leads/${id}`) })
  const [dialog, setDialog] = useState<string | null>(null)
  const lead = q.data
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['lead', id] })
    qc.invalidateQueries({ queryKey: ['leads'] })
  }
  if (q.isLoading) return <Spinner />
  if (q.error || !lead) return <Empty text={errorText(q.error) || 'Lead not found.'} />

  const statusFields = (to: string): FieldDef[] => {
    if (to === 'qualified')
      return [
        { name: 'need', label: 'Need - what do they want?', type: 'textarea', required: true },
        { name: 'fit', label: 'Fit - why are we right for it?', type: 'textarea', required: true },
      ]
    if (to === 'nurture') return [{ name: 'nurture_review_date', label: 'Review again on', type: 'date', required: true }]
    if (to === 'disqualified') return [{ name: 'disqualify_reason', label: 'Reason', type: 'textarea', required: true }]
    return [{ name: 'reason', label: 'Note (optional)' }]
  }

  const contact = lead.contact
  return (
    <>
      <PageHead
        title={contact.name || contact.company_name}
        sub={
          <span className="flex">
            {contact.name && contact.company_name} <StatusBadge value={lead.status} labelText={lead.status_label} /> {lead.days_in_status} day(s) in status
          </span>
        }
        actions={
          <>
            <button className="btn" onClick={() => setDialog('nurture')}>
              Nurture
            </button>
            <button className="btn" onClick={() => setDialog('disqualified')}>
              Disqualify
            </button>
            <button className="btn primary" onClick={() => setDialog('deal')}>
              <Plus size={15} /> Create deal
            </button>
          </>
        }
      />
      <StageBar stages={LEAD_FLOW} current={lead.status} onPick={(s) => setDialog(s)} doneUntil={LEAD_FLOW.findIndex((s) => s.value === lead.status)} />
      <div className="grid detail">
        <div className="stack">
          <Card title="Contact" actions={<button className="btn sm ghost" onClick={() => setDialog('contact')}>Edit</button>}>
            <dl className="kv">
              <dt>Name</dt>
              <dd>{contact.name || '—'}</dd>
              <dt>Company</dt>
              <dd>{contact.company_name || '—'}</dd>
              <dt>Title</dt>
              <dd>{contact.title || '—'}</dd>
              <dt>Email</dt>
              <dd>{contact.email ? <a className="link" href={`mailto:${contact.email}`}>{contact.email}</a> : '—'}</dd>
              <dt>Phone</dt>
              <dd>{contact.phone ? <a className="link" href={`tel:${contact.phone_normalized || contact.phone}`}>{contact.phone}</a> : '—'}</dd>
              <dt>LinkedIn</dt>
              <dd>{contact.linkedin_url ? <a className="link" href={contact.linkedin_url} target="_blank" rel="noreferrer">Profile</a> : '—'}</dd>
              <dt>Website</dt>
              <dd>{contact.website || '—'}</dd>
            </dl>
          </Card>
          <Card title="Lead" actions={<button className="btn sm ghost" onClick={() => setDialog('edit')}>Edit</button>}>
            <dl className="kv">
              <dt>Owner</dt>
              <dd>
                <Person m={lead.owner} />
              </dd>
              <dt>Source</dt>
              <dd>
                {lead.source || '—'} {lead.source_reference && <div className="muted small">{lead.source_reference}</div>}
              </dd>
              <dt>Next action</dt>
              <dd>
                {lead.next_action || '—'}
                {lead.next_action_due && <div className={`small ${lead.next_action_overdue ? 'overdue' : 'muted'}`}>{fmtDateTime(lead.next_action_due)}</div>}
              </dd>
              <dt>Need</dt>
              <dd className="pre">{lead.need || '—'}</dd>
              <dt>Fit</dt>
              <dd className="pre">{lead.fit || '—'}</dd>
              {lead.nurture_review_date && (
                <>
                  <dt>Review on</dt>
                  <dd>{fmtDate(lead.nurture_review_date)}</dd>
                </>
              )}
              {lead.disqualify_reason && (
                <>
                  <dt>Disqualified</dt>
                  <dd>{lead.disqualify_reason}</dd>
                </>
              )}
              <dt>Shared with</dt>
              <dd>{lead.shared_with.length ? lead.shared_with.map((m: any) => m.name).join(', ') : '—'}</dd>
            </dl>
            {me.capabilities.sales_manage && (
              <button className="btn sm" style={{ marginTop: 10 }} onClick={() => setDialog('share')}>
                Share with…
              </button>
            )}
          </Card>
          <Card title={`Deals (${lead.opportunities.length})`} pad={false}>
            {lead.opportunities.length ? (
              lead.opportunities.map((o: any) => (
                <Link key={o.id} to={`/deals/${o.id}`} className="task" style={{ display: 'flex' }}>
                  <div style={{ flex: 1 }}>
                    <div className="ttl">{o.title}</div>
                    <div className="meta">{money(o.value, o.currency)}</div>
                  </div>
                  <StatusBadge value={o.stage} labelText={o.stage_label} />
                </Link>
              ))
            ) : (
              <Empty text="No deals yet." />
            )}
          </Card>
          <Card title="Status history" pad={false}>
            <History items={lead.history} />
          </Card>
        </div>
        <div className="stack">
          <AIPanel entityType="lead" entityId={lead.id} />
          <TaskList filter={{ lead: lead.id }} linkTo={{ lead_id: lead.id }} title="Follow-ups" />
          <Timeline target={{ lead_id: lead.id }} />
        </div>
      </div>

      {dialog && LEAD_STATUSES.some((s) => s.value === dialog) && (
        <FormModal
          title={`Move to ${label(LEAD_STATUSES, dialog)}`}
          fields={statusFields(dialog)}
          initial={{ need: lead.need, fit: lead.fit }}
          onClose={() => setDialog(null)}
          onSubmit={(v) => post(`/leads/${lead.id}/status`, { ...v, status: dialog, version: lead.version }).then(() => { toast('Status updated'); refresh() })}
        />
      )}
      {dialog === 'edit' && (
        <FormModal
          title="Edit lead"
          fields={[
            ...(me.capabilities.sales_manage ? [{ name: 'owner_id', label: 'Owner', type: 'member' as const, roles: SALES_ROLES }] : []),
            { name: 'reassign_reason', label: 'Reason for changing owner', show: (v: any) => !!lead.owner && v.owner_id !== lead.owner?.id },
            { name: 'source', label: 'Source', half: true },
            { name: 'source_reference', label: 'Source reference', half: true },
            { name: 'next_action', label: 'Next action', half: true },
            { name: 'next_action_due', label: 'Due', type: 'datetime', half: true },
            { name: 'need', label: 'Need', type: 'textarea' },
            { name: 'fit', label: 'Fit', type: 'textarea' },
          ]}
          initial={{
            owner_id: lead.owner?.id || '', source: lead.source, source_reference: lead.source_reference, next_action: lead.next_action,
            next_action_due: toLocalInput(lead.next_action_due), need: lead.need, fit: lead.fit,
          }}
          onClose={() => setDialog(null)}
          onSubmit={(v) => {
            const body: any = { ...v, version: lead.version }
            if (!me.capabilities.sales_manage) delete body.owner_id
            return patch(`/leads/${lead.id}`, body).then(() => { toast('Saved'); refresh() })
          }}
        />
      )}
      {dialog === 'contact' && (
        <FormModal
          title="Edit contact"
          wide
          fields={[
            { name: 'name', label: 'Name', half: true },
            { name: 'company_name', label: 'Company', half: true },
            { name: 'title', label: 'Job title', half: true },
            { name: 'email', label: 'Email', type: 'email', half: true },
            { name: 'phone', label: 'Phone', half: true },
            { name: 'country', label: 'Country (2 letters)', half: true },
            { name: 'linkedin_url', label: 'LinkedIn', half: true },
            { name: 'website', label: 'Website', half: true },
            { name: 'notes', label: 'Notes', type: 'textarea' },
          ]}
          initial={contact}
          onClose={() => setDialog(null)}
          onSubmit={(v) => patch(`/contacts/${contact.id}`, v).then(() => { toast('Contact saved'); refresh() })}
        />
      )}
      {dialog === 'share' && (
        <FormModal
          title="Share lead"
          intro="Shared representatives can see and work on this lead."
          fields={[{ name: 'member_ids', label: 'Team members', type: 'multimember', roles: ['sales_rep', 'sales_manager'] }]}
          initial={{ member_ids: lead.shared_with.map((m: any) => m.id) }}
          onClose={() => setDialog(null)}
          onSubmit={(v) => post(`/leads/${lead.id}/share`, v).then(refresh)}
        />
      )}
      {dialog === 'deal' && (
        <FormModal
          title="Create deal"
          fields={[
            { name: 'title', label: 'Deal title', required: true, placeholder: 'e.g. Website redesign' },
            { name: 'service', label: 'Service / offer', placeholder: 'Web development, SEO, AI solution…' },
            { name: 'value', label: 'Value (leave empty if unknown)', type: 'number', half: true },
            { name: 'currency', label: 'Currency', type: 'select', options: CURRENCIES.map((c) => ({ value: c, label: c })), half: true },
            { name: 'expected_close_date', label: 'Expected close', type: 'date', half: true },
            { name: 'next_action_due', label: 'Next action due', type: 'datetime', half: true },
            { name: 'next_action', label: 'Next action' },
            ...(!lead.need ? [{ name: 'need', label: 'Need', type: 'textarea' as const }] : []),
            ...(!lead.fit ? [{ name: 'fit', label: 'Fit', type: 'textarea' as const }] : []),
          ]}
          initial={{ currency: me.workspace.default_currency }}
          onClose={() => setDialog(null)}
          onSubmit={(v) => {
            const body: any = { ...v, lead_id: lead.id }
            if (!body.value) {
              delete body.value
              body.currency = ''
            }
            return post('/opportunities', body).then((o) => {
              toast('Deal created')
              nav(`/deals/${o.id}`)
            })
          }}
        />
      )}
      {lead.status === 'disqualified' && <div className="notice" style={{ marginTop: 16 }}>This lead is disqualified. <Badge>{lead.disqualify_reason}</Badge></div>}
    </>
  )
}
