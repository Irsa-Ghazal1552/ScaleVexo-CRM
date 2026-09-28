import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Clock3, Columns3, List, MoreHorizontal, Plus } from 'lucide-react'
import { get, Paged, patch, post, qs } from '../lib/api'
import { useMe } from '../lib/auth'
import { CURRENCIES, fmtDate, fmtDateTime, label, money, STAGES, toLocalInput } from '../lib/format'
import { Avatar, Card, Empty, errorText, FieldDef, FormModal, PageHead, Person, Segmented, Spinner, StatusBadge, useToast } from '../components/ui'
import { AIPanel, History, StageBar, TaskList, Timeline } from '../components/work'

const SALES_ROLES = ['owner', 'sales_manager', 'sales_rep']
const STAGE_COLORS: Record<string, string> = {
  discovery: 'var(--stage-1)',
  qualified: 'var(--stage-2)',
  proposal: 'var(--stage-3)',
  negotiation: 'var(--stage-4)',
  won: 'var(--stage-won)',
  lost: 'var(--stage-lost)',
}

export function winFields(): FieldDef[] {
  return [
    { name: 'scope', label: 'Accepted scope (what was agreed)', type: 'textarea', required: true },
    { name: 'exclusions', label: 'Exclusions (what is not included)', type: 'textarea' },
    { name: 'commercial_reference', label: 'Commercial reference', required: true, placeholder: 'Signed proposal no., PO, contract link', half: true },
    { name: 'delivery_owner_id', label: 'Delivery owner', type: 'member', roles: ['delivery_manager', 'delivery_employee', 'owner'], required: true, half: true },
    { name: 'commercial_decision', label: 'Commercial decision', required: true, placeholder: 'Who approved, on what terms (e.g. CEO approved, 50% advance)' },
    { name: 'client_contacts', label: 'Client contacts for delivery', type: 'textarea' },
    { name: 'promised_start', label: 'Promised start', type: 'date', half: true },
    { name: 'promised_end', label: 'Promised delivery', type: 'date', half: true },
    { name: 'promised_dates_note', label: 'Other promised dates' },
  ]
}

function stageFields(to: string, deal: any): FieldDef[] {
  if (to === 'lost') return [{ name: 'reason', label: 'Why was it lost?', type: 'textarea', required: true }]
  if ((to === 'proposal' || to === 'negotiation') && !deal.scope_reference)
    return [{ name: 'scope_reference', label: 'Scope / proposal reference', required: true, placeholder: 'Proposal number or document link' }]
  if (deal.stage === 'lost') return [{ name: 'reason', label: 'Why is this deal being reopened?', required: true }]
  return []
}

export function useStageMove(onDone: () => void) {
  const toast = useToast()
  const [pending, setPending] = useState<{ deal: any; to: string } | null>(null)
  const move = async (deal: any, to: string) => {
    if (to === deal.stage) return
    if (to === 'won' || stageFields(to, deal).length) {
      setPending({ deal, to })
      return
    }
    try {
      await post(`/opportunities/${deal.id}/stage`, { stage: to, version: deal.version })
      toast(`Moved to ${label(STAGES, to)}`)
      onDone()
    } catch (e) {
      toast(errorText(e), 'error')
      onDone()
    }
  }
  const dialog = pending ? (
    <FormModal
      title={pending.to === 'won' ? `Close as won: ${pending.deal.title}` : `Move to ${label(STAGES, pending.to)}`}
      wide={pending.to === 'won'}
      intro={
        pending.to === 'won'
          ? 'Winning a deal creates the client record and an onboarding project, and asks the delivery owner to accept the handover. Won does not mean paid.'
          : undefined
      }
      fields={pending.to === 'won' ? winFields() : stageFields(pending.to, pending.deal)}
      initial={pending.to === 'won' ? { commercial_reference: pending.deal.scope_reference } : {}}
      submitLabel={pending.to === 'won' ? 'Close as won' : 'Move'}
      onClose={() => setPending(null)}
      onSubmit={(v) =>
        post(`/opportunities/${pending.deal.id}/stage`, { ...v, stage: pending.to, version: pending.deal.version }).then(() => {
          toast(pending.to === 'won' ? 'Deal won - handover sent to delivery' : `Moved to ${label(STAGES, pending.to)}`)
          onDone()
        })
      }
    />
  ) : null
  return { move, dialog }
}

function DealCard({ d, onMove, commercials }: { d: any; onMove: (to: string) => void; commercials: boolean }) {
  const nav = useNavigate()
  const [menu, setMenu] = useState(false)
  return (
    <div
      className="kcard"
      draggable
      onDragStart={(e) => e.dataTransfer.setData('text/plain', d.id)}
      onClick={() => nav(`/deals/${d.id}`)}
    >
      <div className="flex between">
        {/* The title is the keyboard/screen-reader way in; the whole card stays clickable for the mouse. */}
        <Link className="t" to={`/deals/${d.id}`} onClick={(e) => e.stopPropagation()}>
          {d.title}
        </Link>
        <div style={{ position: 'relative' }} onClick={(e) => e.stopPropagation()}>
          <button className="icon-btn" aria-label="Move deal" onClick={() => setMenu(!menu)}>
            <MoreHorizontal size={16} />
          </button>
          {menu && (
            <div className="card" style={{ position: 'absolute', right: 0, top: 26, zIndex: 5, width: 170, padding: 4 }}>
              <div className="muted small" style={{ padding: '4px 8px' }}>Move to…</div>
              {STAGES.filter((s) => s.value !== d.stage).map((s) => (
                <button
                  key={s.value}
                  className="btn ghost sm"
                  style={{ width: '100%', justifyContent: 'flex-start' }}
                  onClick={() => {
                    setMenu(false)
                    onMove(s.value)
                  }}
                >
                  {s.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="c">{d.contact.label}</div>
      {commercials && <div className="v">{money(d.value, d.currency)}</div>}
      <div className="foot">
        <Avatar name={d.owner?.name} size="sm" />
        <span>
          <Clock3 size={12} /> {d.days_in_stage}d in stage
        </span>
        {d.stage !== 'won' && d.stage !== 'lost' && (
          <span className={d.next_action_overdue ? 'overdue' : ''} style={{ marginLeft: 'auto' }}>
            {d.next_action_overdue ? 'No next action' : fmtDate(d.next_action_due)}
          </span>
        )}
      </div>
    </div>
  )
}

export function DealsPage() {
  const me = useMe()
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const view = params.get('view') || 'board'
  const owner = params.get('owner') || (me.capabilities.sales_manage ? '' : 'me')
  const q = params.get('q') || ''
  const [over, setOver] = useState('')
  const [creating, setCreating] = useState(false)
  const board = useQuery({ queryKey: ['pipeline', owner, q], queryFn: () => get<any>('/opportunities/pipeline' + qs({ owner, q })), enabled: view === 'board' })
  const list = useQuery({ queryKey: ['deals', owner, q], queryFn: () => get<Paged<any>>('/opportunities' + qs({ owner, q, page_size: 200 })), enabled: view === 'list' })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['pipeline'] })
    qc.invalidateQueries({ queryKey: ['deals'] })
  }
  const { move, dialog } = useStageMove(refresh)
  const leads = useQuery({ queryKey: ['leads-for-deal'], queryFn: () => get<Paged<any>>('/leads?page_size=500'), enabled: creating })
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params)
    if (v) next.set(k, v)
    else next.delete(k)
    setParams(next)
  }
  const byStage = useMemo(() => {
    const m: Record<string, any[]> = {}
    STAGES.forEach((s) => (m[s.value] = []))
    ;(board.data?.deals || []).forEach((d: any) => m[d.stage]?.push(d))
    return m
  }, [board.data])
  const sums: Record<string, any> = {}
  ;(board.data?.summary.stages || []).forEach((s: any) => (sums[s.stage] = s))

  return (
    <>
      <PageHead
        title="Deals"
        sub="Pipeline totals are shown per currency and never combined."
        actions={
          <button className="btn primary" onClick={() => setCreating(true)}>
            <Plus size={16} /> Deal
          </button>
        }
      />
      <div className="toolbar">
        <Segmented
          options={[
            { value: 'board', label: <span className="flex"><Columns3 size={14} /> Pipeline</span> },
            { value: 'list', label: <span className="flex"><List size={14} /> List</span> },
          ]}
          value={view}
          onChange={(v) => set('view', v === 'board' ? '' : v)}
        />
        <input className="input grow" placeholder="Search deals…" defaultValue={q} onKeyDown={(e) => e.key === 'Enter' && set('q', (e.target as HTMLInputElement).value)} />
        {me.capabilities.sales_manage && (
          <Segmented options={[{ value: '', label: 'All deals' }, { value: 'me', label: 'Mine' }]} value={owner} onChange={(v) => set('owner', v)} />
        )}
      </div>

      {view === 'board' ? (
        board.isLoading ? (
          <Spinner />
        ) : (
          <div className="kanban">
            {STAGES.map((s) => (
              <div className="kcol" key={s.value}>
                <div className="kcol-head" style={{ background: STAGE_COLORS[s.value], color: s.value === 'lost' ? '#222' : '#fff' }}>
                  {s.label}
                  <span className="n">{byStage[s.value].length}</span>
                </div>
                <div className="kcol-sum">
                  {[
                    ...(me.capabilities.commercials ? Object.entries(sums[s.value]?.totals || {}).map(([cur, val]) => money(val as string, cur)) : []),
                    ...(sums[s.value]?.unknown_value_count ? [`${sums[s.value].unknown_value_count} with unknown value`] : []),
                    ...(s.value === 'won' || s.value === 'lost' ? ['last 30 days'] : []),
                  ].join(' · ')}
                </div>
                <div
                  className={`kcol-body ${over === s.value ? 'over' : ''}`}
                  onDragOver={(e) => {
                    e.preventDefault()
                    setOver(s.value)
                  }}
                  onDragLeave={() => setOver('')}
                  onDrop={(e) => {
                    e.preventDefault()
                    setOver('')
                    const id = e.dataTransfer.getData('text/plain')
                    const deal = (board.data?.deals || []).find((d: any) => d.id === id)
                    if (deal) move(deal, s.value)
                  }}
                >
                  {byStage[s.value].map((d) => (
                    <DealCard key={d.id} d={d} commercials={me.capabilities.commercials} onMove={(to) => move(d, to)} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )
      ) : list.isLoading ? (
        <Spinner />
      ) : (
        <div className="table-wrap">
          {!list.data?.results.length ? (
            <Empty text="No deals yet." />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Deal</th>
                  <th>Stage</th>
                  <th>Value</th>
                  <th>Owner</th>
                  <th>Days in stage</th>
                  <th>Next action</th>
                  <th>Expected close</th>
                </tr>
              </thead>
              <tbody>
                {list.data.results.map((d) => (
                  <tr key={d.id} className="click" onClick={() => nav(`/deals/${d.id}`)}>
                    <td>
                      <div className="strong">{d.title}</div>
                      <div className="muted small">{d.contact.label}</div>
                    </td>
                    <td>
                      <StatusBadge value={d.stage} labelText={d.stage_label} />
                    </td>
                    <td>{money(d.value, d.currency)}</td>
                    <td>
                      <Person m={d.owner} />
                    </td>
                    <td>{d.days_in_stage}</td>
                    <td className={d.next_action_overdue ? 'overdue' : ''}>
                      {d.next_action || (d.stage === 'won' || d.stage === 'lost' ? '—' : 'None')}
                      {d.next_action_due && <div className="small">{fmtDateTime(d.next_action_due)}</div>}
                    </td>
                    <td>{fmtDate(d.expected_close_date)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
      {dialog}
      {creating && (
        <FormModal
          title="New deal"
          fields={[
            {
              name: 'lead_id',
              label: 'Lead',
              type: 'select',
              required: true,
              options: (leads.data?.results || []).map((l: any) => ({ value: l.id, label: `${l.contact.label} (${l.status_label})` })),
              hint: leads.isLoading ? 'Loading leads…' : 'Create the lead first if it is not in the list.',
            },
            { name: 'title', label: 'Deal title', required: true },
            { name: 'service', label: 'Service / offer' },
            { name: 'value', label: 'Value (empty = unknown)', type: 'number', half: true },
            { name: 'currency', label: 'Currency', type: 'select', options: CURRENCIES.map((c) => ({ value: c, label: c })), half: true },
            { name: 'next_action', label: 'Next action', half: true },
            { name: 'next_action_due', label: 'Due', type: 'datetime', half: true },
          ]}
          initial={{ currency: me.workspace.default_currency }}
          onClose={() => setCreating(false)}
          onSubmit={(v) => {
            const body: any = { ...v }
            if (!body.value) {
              delete body.value
              body.currency = ''
            }
            return post('/opportunities', body).then((o) => {
              toast('Deal created')
              refresh()
              nav(`/deals/${o.id}`)
            })
          }}
        />
      )}
    </>
  )
}

export function DealDetailPage() {
  const { id } = useParams()
  const me = useMe()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['deal', id], queryFn: () => get<any>(`/opportunities/${id}`) })
  const [editing, setEditing] = useState(false)
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['deal', id] })
    qc.invalidateQueries({ queryKey: ['pipeline'] })
    qc.invalidateQueries({ queryKey: ['tasks'] })
  }
  const { move, dialog } = useStageMove(refresh)
  const d = q.data
  if (q.isLoading) return <Spinner />
  if (q.error || !d) return <Empty text={errorText(q.error) || 'Deal not found.'} />
  const canEdit = me.capabilities.sales
  const closed = d.stage === 'won' || d.stage === 'lost'

  return (
    <>
      <PageHead
        title={d.title}
        sub={
          <span className="flex wrap">
            {d.contact.label}
            {d.lead_id && (
              <Link className="link" to={`/leads/${d.lead_id}`}>
                Open lead
              </Link>
            )}
            <StatusBadge value={d.stage} labelText={d.stage_label} /> {d.days_in_stage} day(s) in stage
          </span>
        }
        actions={
          canEdit && !closed ? (
            <>
              <button className="btn" onClick={() => move(d, 'lost')}>
                Close as lost
              </button>
              <button className="btn primary" onClick={() => move(d, 'won')}>
                Close as won
              </button>
            </>
          ) : d.stage === 'lost' && canEdit ? (
            <button className="btn" onClick={() => move(d, 'discovery')}>
              Reopen
            </button>
          ) : null
        }
      />
      <StageBar stages={STAGES} current={d.stage} onPick={canEdit && d.stage !== 'won' ? (s) => move(d, s) : undefined} />
      {d.handover && (
        <div className="notice dark" style={{ marginBottom: 14 }}>
          Handover to delivery: <b>{d.handover.status}</b> ·{' '}
          <Link className="link" to={`/clients/${d.handover.client_id}`}>
            client record
          </Link>
          {d.handover.project_id && (
            <>
              {' · '}
              <Link className="link" to={`/projects/${d.handover.project_id}`}>
                onboarding project
              </Link>
            </>
          )}
        </div>
      )}
      <div className="grid detail">
        <div className="stack">
          <Card title="Deal" actions={canEdit && !closed ? <button className="btn sm ghost" onClick={() => setEditing(true)}>Edit</button> : undefined}>
            <dl className="kv">
              <dt>Value</dt>
              <dd className="strong">{money(d.value, d.currency)}</dd>
              <dt>Service</dt>
              <dd>{d.service || '—'}</dd>
              <dt>Owner</dt>
              <dd>
                <Person m={d.owner} />
              </dd>
              <dt>Expected close</dt>
              <dd>{fmtDate(d.expected_close_date)}</dd>
              <dt>Next action</dt>
              <dd className={d.next_action_overdue ? 'overdue' : ''}>
                {d.next_action || (closed ? '—' : 'None scheduled')}
                {d.next_action_due && <div className="small">{fmtDateTime(d.next_action_due)}</div>}
              </dd>
              <dt>Scope reference</dt>
              <dd className="pre">{d.scope_reference || '—'}</dd>
              {d.lost_reason && (
                <>
                  <dt>Lost because</dt>
                  <dd>{d.lost_reason}</dd>
                </>
              )}
              {d.commercial_decision && (
                <>
                  <dt>Decision</dt>
                  <dd>{d.commercial_decision}</dd>
                </>
              )}
              <dt>Contact</dt>
              <dd>
                {d.contact.email || d.contact.phone || '—'}
              </dd>
            </dl>
          </Card>
          <Card title="Stage history" pad={false}>
            <History items={d.history} />
          </Card>
        </div>
        <div className="stack">
          {canEdit && <AIPanel entityType="opportunity" entityId={d.id} />}
          {!closed && <TaskList filter={{ opportunity: d.id }} linkTo={{ opportunity_id: d.id }} title="Follow-ups" />}
          <Timeline target={{ opportunity_id: d.id }} allowLog={canEdit} />
        </div>
      </div>
      {dialog}
      {editing && (
        <FormModal
          title="Edit deal"
          fields={[
            { name: 'title', label: 'Title', required: true },
            { name: 'service', label: 'Service / offer' },
            { name: 'value', label: 'Value (empty = unknown)', type: 'number', half: true },
            { name: 'currency', label: 'Currency', type: 'select', options: CURRENCIES.map((c) => ({ value: c, label: c })), half: true },
            { name: 'expected_close_date', label: 'Expected close', type: 'date', half: true },
            ...(me.capabilities.sales_manage ? [{ name: 'owner_id', label: 'Owner', type: 'member' as const, roles: SALES_ROLES, half: true }] : []),
            { name: 'reassign_reason', label: 'Reason for new owner', show: (v: any) => !!d.owner && !!v.owner_id && v.owner_id !== d.owner?.id },
            { name: 'next_action', label: 'Next action', half: true },
            { name: 'next_action_due', label: 'Due', type: 'datetime', half: true },
            { name: 'scope_reference', label: 'Scope / proposal reference' },
          ]}
          initial={{
            title: d.title, service: d.service, value: d.value ?? '', currency: d.currency, expected_close_date: d.expected_close_date || '',
            owner_id: d.owner?.id || '', next_action: d.next_action, next_action_due: toLocalInput(d.next_action_due), scope_reference: d.scope_reference,
          }}
          onClose={() => setEditing(false)}
          onSubmit={(v) => {
            const body: any = { ...v, version: d.version }
            if (body.value === '') body.value = null
            if (!me.capabilities.sales_manage) delete body.owner_id
            return patch(`/opportunities/${d.id}`, body).then(() => {
              toast('Saved')
              refresh()
            })
          }}
        />
      )}
    </>
  )
}
