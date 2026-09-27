import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { get, post, qs } from '../lib/api'
import { useMe } from '../lib/auth'
import { CURRENCIES, entityPath, fmtDate, fmtDateTime, money } from '../lib/format'
import { Card, Empty, FormModal, PageHead, Spinner, Tabs, useToast } from '../components/ui'

const REPORTS = [
  { value: 'neglected-leads', label: 'Neglected leads', sales: true },
  { value: 'overdue-next-actions', label: 'Overdue next actions', sales: true },
  { value: 'stage-aging', label: 'Stage aging', sales: true },
  { value: 'conversion-by-source', label: 'Conversion by source', sales: true },
  { value: 'won-deals', label: 'Won deals', sales: true },
  { value: 'delivery-blockers', label: 'Delivery blockers', sales: false },
  { value: 'reopened-tickets', label: 'Reopened tickets', sales: false },
]

function Currencies({ data }: { data?: any }) {
  if (!data) return <span className="muted">—</span>
  const entries = Object.entries(data.by_currency || {})
  return (
    <>
      {entries.length === 0 && <div className="v">0</div>}
      {entries.map(([cur, v]: any) => (
        <div className="v" key={cur} style={{ fontSize: entries.length > 1 ? 20 : 26 }}>
          {money(v.total, cur)}
        </div>
      ))}
      <div className="s">
        {data.count} record(s){data.unknown_value_count ? ` · ${data.unknown_value_count} with unknown value` : ''}
      </div>
    </>
  )
}

export default function ReportsPage() {
  const me = useMe()
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [report, setReport] = useState('')
  const [tab, setTab] = useState('overview')
  const [addingReceipt, setAddingReceipt] = useState(false)
  const overview = useQuery({ queryKey: ['overview', from, to], queryFn: () => get<any>('/reports/overview' + qs({ from, to })) })
  const detail = useQuery({ queryKey: ['report', report, from, to], queryFn: () => get<any>(`/reports/${report}` + qs({ from, to })), enabled: !!report })
  const receipts = useQuery({ queryKey: ['receipts'], queryFn: () => get<any[]>('/receipts'), enabled: tab === 'receipts' })
  const s = overview.data?.sections || {}
  const available = REPORTS.filter((r) => (r.sales ? me.capabilities.sales_manage : me.capabilities.delivery_manage || me.membership.role === 'owner'))

  const tile = (k: string, v: any, sub: string, rep?: string, dark?: boolean) => (
    <div className={`tile ${rep ? 'click' : ''} ${dark && v ? 'dark' : ''}`} onClick={() => rep && (setReport(rep), setTab('overview'))}>
      <div className="k">{k}</div>
      <div className="v">{v ?? '—'}</div>
      <div className="s">{sub}</div>
    </div>
  )

  return (
    <>
      <PageHead title="Reports" sub="Every figure shows its filter and period, and opens the records behind it." />
      <div className="toolbar">
        <span className="muted">Period</span>
        <input className="input" type="date" style={{ width: 170 }} value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From" />
        <input className="input" type="date" style={{ width: 170 }} value={to} onChange={(e) => setTo(e.target.value)} aria-label="To" />
        {overview.data && (
          <span className="muted small">
            {overview.data.filters.from} → {overview.data.filters.to} ({overview.data.filters.timezone})
          </span>
        )}
      </div>
      <Tabs
        tabs={[{ value: 'overview', label: 'CEO overview' }, ...(me.capabilities.receipts || me.capabilities.sales_manage ? [{ value: 'receipts', label: 'Cash receipts' }] : [])]}
        value={tab}
        onChange={setTab}
      />
      {tab === 'overview' &&
        (overview.isLoading ? (
          <Spinner />
        ) : (
          <div className="stack">
            {(s.pipeline || s.won) && (
              <div className="grid tiles">
                {s.pipeline && (
                  <div className="tile dark">
                    <div className="k">Open pipeline</div>
                    <Currencies data={s.pipeline} />
                  </div>
                )}
                {s.won && (
                  <div className="tile click" onClick={() => setReport('won-deals')}>
                    <div className="k">Won contract value</div>
                    <Currencies data={s.won} />
                    <div className="s">{s.won.lost_count} lost in period · not cash</div>
                  </div>
                )}
                {s.receipts && (
                  <div className="tile click" onClick={() => setTab('receipts')}>
                    <div className="k">Cash received</div>
                    <Currencies data={s.receipts} />
                  </div>
                )}
              </div>
            )}
            {s.sales_exceptions && (
              <>
                <h3 style={{ marginTop: 8 }}>Sales exceptions</h3>
                <div className="grid tiles">
                  {tile('Neglected leads', s.sales_exceptions.neglected_leads, 'no activity for 7+ days', 'neglected-leads', true)}
                  {tile('Deals without next action', s.sales_exceptions.overdue_next_actions, 'or next action overdue', 'overdue-next-actions', true)}
                  {tile('Unassigned leads', s.sales_exceptions.unassigned_leads, 'need an owner', 'neglected-leads')}
                  {tile('Stale deals', s.sales_exceptions.stale_deals_30d, '30+ days in the same stage', 'stage-aging')}
                </div>
              </>
            )}
            {s.delivery && (
              <>
                <h3 style={{ marginTop: 8 }}>Delivery</h3>
                <div className="grid tiles">
                  {tile('Handovers waiting', s.delivery.handovers_waiting, 'pending, returned or exception', 'delivery-blockers', true)}
                  {tile('Blocked milestones', s.delivery.blocked_milestones, 'need a decision', 'delivery-blockers', true)}
                  {tile('Overdue milestones', s.delivery.overdue_milestones, 'past their due date', 'delivery-blockers')}
                  {tile('Open tickets', s.delivery.open_tickets, `${s.delivery.critical_tickets} critical`)}
                  {tile('Reopened tickets', s.delivery.reopened_tickets_in_period, 'in period', 'reopened-tickets')}
                </div>
              </>
            )}
            {s.operating_cost && (
              <>
                <h3 style={{ marginTop: 8 }}>Operating cost</h3>
                <div className="grid tiles">
                  {tile('AI spend this month', `$${s.operating_cost.ai.spent_usd}`, `of $${s.operating_cost.ai.budget_usd} budget · ${s.operating_cost.ai.requests} requests`)}
                </div>
              </>
            )}
            <div className="flex wrap" style={{ marginTop: 8 }}>
              {available.map((r) => (
                <button key={r.value} className={`btn sm ${report === r.value ? 'primary' : ''}`} onClick={() => setReport(r.value)}>
                  {r.label}
                </button>
              ))}
            </div>
            {report && (
              <Card title={`${REPORTS.find((r) => r.value === report)?.label} (${detail.data?.count ?? '…'})`} pad={false}>
                {detail.isLoading ? (
                  <Spinner />
                ) : !detail.data?.rows.length ? (
                  <Empty text="No records match." />
                ) : (
                  <div style={{ overflowX: 'auto' }}>
                    <div className="card-body small muted">Filter: {Object.entries(detail.data.filters).map(([k, v]) => `${k}=${v}`).join(' · ')}</div>
                    <table className="table">
                      <thead>
                        <tr>
                          {Object.keys(detail.data.rows[0])
                            .filter((k) => !['id', 'type'].includes(k))
                            .map((k) => (
                              <th key={k}>{k.replace(/_/g, ' ')}</th>
                            ))}
                        </tr>
                      </thead>
                      <tbody>
                        {detail.data.rows.map((r: any, i: number) => (
                          <tr key={i} className={r.id ? 'click' : ''} onClick={() => r.id && nav(entityPath(r.type, r.id))}>
                            {Object.entries(r)
                              .filter(([k]) => !['id', 'type'].includes(k))
                              .map(([k, v]: any) => (
                                <td key={k}>{typeof v === 'string' && /^\d{4}-\d\d-\d\dT/.test(v) ? fmtDateTime(v) : v === null ? '—' : String(v)}</td>
                              ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            )}
          </div>
        ))}
      {tab === 'receipts' && (
        <Card
          title="Cash receipts register"
          actions={me.capabilities.receipts ? <button className="btn sm primary" onClick={() => setAddingReceipt(true)}>+ Receipt</button> : undefined}
          pad={false}
        >
          <div className="card-body">
            <div className="notice">Operational register of money received. It is not an accounting ledger or bank reconciliation.</div>
          </div>
          {receipts.isLoading ? (
            <Spinner />
          ) : !receipts.data?.length ? (
            <Empty text="No receipts recorded." />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Amount</th>
                  <th>Client</th>
                  <th>Deal</th>
                  <th>Evidence</th>
                  <th>Recorded by</th>
                </tr>
              </thead>
              <tbody>
                {receipts.data.map((r) => (
                  <tr key={r.id}>
                    <td>{fmtDate(r.received_on)}</td>
                    <td className="strong">{money(r.amount, r.currency)}</td>
                    <td>{r.client_name || '—'}</td>
                    <td>{r.opportunity_title || '—'}</td>
                    <td>{r.evidence_reference}</td>
                    <td>{r.recorded_by?.name}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
      {addingReceipt && (
        <FormModal
          title="Record cash receipt"
          fields={[
            { name: 'amount', label: 'Amount', type: 'number', required: true, half: true },
            { name: 'currency', label: 'Currency', type: 'select', options: CURRENCIES.map((c) => ({ value: c, label: c })), required: true, half: true },
            { name: 'received_on', label: 'Date received', type: 'date', required: true },
            { name: 'evidence_reference', label: 'Evidence (bank ref, invoice no.)', required: true },
            { name: 'note', label: 'Note' },
          ]}
          initial={{ currency: me.workspace.default_currency, received_on: new Date().toISOString().slice(0, 10) }}
          onClose={() => setAddingReceipt(false)}
          onSubmit={(v) =>
            post('/receipts', v).then(() => {
              toast('Receipt recorded')
              qc.invalidateQueries({ queryKey: ['receipts'] })
              qc.invalidateQueries({ queryKey: ['overview'] })
            })
          }
        />
      )}
    </>
  )
}
