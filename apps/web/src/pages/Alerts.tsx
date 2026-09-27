import { useState } from 'react'
import { Link } from 'react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BellOff } from 'lucide-react'
import { get, Paged, post } from '../lib/api'
import { useMe } from '../lib/auth'
import { entityPath, fmtDateTime } from '../lib/format'
import { Badge, Empty, errorText, FormModal, PageHead, Person, Segmented, Spinner, useToast } from '../components/ui'

export function AlertList({ alerts, onChanged, compact, showRecipient }: { alerts: any[]; onChanged: () => void; compact?: boolean; showRecipient?: boolean }) {
  const toast = useToast()
  const [dialog, setDialog] = useState<{ alert: any; action: 'resolve' | 'challenge' } | null>(null)
  if (!alerts.length) return <Empty text="No open alerts." icon={<BellOff size={26} />} />
  const act = (a: any, action: string, body: any = {}) =>
    post(`/alerts/${a.id}/${action}`, body)
      .then(() => {
        onChanged()
      })
  return (
    <div>
      {alerts.map((a) => (
        <div key={a.id} className={`alert-item ${a.severity}`}>
          <div className="bar" />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="flex wrap">
              <Link to={entityPath(a.entity_type, a.entity_id)} className="strong">
                {a.title}
              </Link>
              {a.rule_code && <Badge tone="outline">{a.rule_code}</Badge>}
              {a.status === 'acknowledged' && <Badge>Acknowledged</Badge>}
              {a.status === 'resolved' && <Badge tone="dark">Resolved</Badge>}
            </div>
            <div className="small" style={{ marginTop: 3 }}>
              <span className="muted">Why: </span>
              {a.cause}
            </div>
            {a.challenge_note && <div className="small" style={{ marginTop: 3 }}>Challenge: {a.challenge_note}</div>}
            {a.resolution_note && <div className="small muted" style={{ marginTop: 3 }}>Resolution: {a.resolution_note}</div>}
            <div className="tl-meta" style={{ marginTop: 5 }}>
              {showRecipient && <Person m={a.recipient} />}
              <span>{fmtDateTime(a.created_at)}</span>
              {a.status !== 'resolved' && (
                <span className="flex" style={{ marginLeft: compact ? 0 : 'auto' }}>
                  {a.status === 'open' && (
                    <button className="btn sm" onClick={() => act(a, 'acknowledge').catch((e) => toast(errorText(e), 'error'))}>
                      Acknowledge
                    </button>
                  )}
                  <button className="btn sm" onClick={() => setDialog({ alert: a, action: 'resolve' })}>
                    Resolve
                  </button>
                  {!compact && (
                    <button className="btn sm ghost" onClick={() => setDialog({ alert: a, action: 'challenge' })}>
                      Challenge
                    </button>
                  )}
                </span>
              )}
            </div>
          </div>
        </div>
      ))}
      {dialog && (
        <FormModal
          title={dialog.action === 'resolve' ? 'Resolve alert' : 'Challenge alert'}
          intro={dialog.action === 'challenge' ? 'Explain why this alert is not right. Your manager will review it.' : undefined}
          fields={[{ name: 'note', label: dialog.action === 'resolve' ? 'What was done?' : 'Explanation', type: 'textarea', required: true }]}
          onClose={() => setDialog(null)}
          onSubmit={(v) => act(dialog.alert, dialog.action, v).then(() => toast(dialog.action === 'resolve' ? 'Alert resolved' : 'Challenge sent'))}
        />
      )}
    </div>
  )
}

export default function AlertsPage() {
  const me = useMe()
  const qc = useQueryClient()
  const [scope, setScope] = useState('mine')
  const [status, setStatus] = useState('open')
  const q = useQuery({ queryKey: ['alerts', scope, status], queryFn: () => get<Paged<any>>(`/alerts?scope=${scope}&status=${status}`) })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['alerts'] })
    qc.invalidateQueries({ queryKey: ['alerts-count'] })
    qc.invalidateQueries({ queryKey: ['today'] })
  }
  return (
    <>
      <PageHead title="Alerts" sub="Every alert explains why it appeared and opens the record behind it." />
      <div className="toolbar">
        {me.capabilities.manager && (
          <Segmented options={[{ value: 'mine', label: 'Mine' }, { value: 'team', label: 'My team (exception view)' }]} value={scope} onChange={setScope} />
        )}
        <Segmented options={[{ value: 'open', label: 'Open' }, { value: 'resolved', label: 'Resolved' }, { value: 'all', label: 'All' }]} value={status} onChange={setStatus} />
      </div>
      <div className="card">{q.isLoading ? <Spinner /> : <AlertList alerts={q.data?.results || []} onChanged={refresh} showRecipient={scope === 'team'} />}</div>
    </>
  )
}
