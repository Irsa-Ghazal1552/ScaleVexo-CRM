import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { get } from '../lib/api'
import { useMe } from '../lib/auth'
import { Card, Empty, PageHead, Person, Spinner, StatusBadge } from '../components/ui'
import { Task, TaskRow } from '../components/work'
import { AlertList } from './Alerts'
import { fmtDate } from '../lib/format'

type Today = {
  overdue: Task[]
  due_today: Task[]
  upcoming: Task[]
  blocked: Task[]
  alerts: any[]
  completed_today: number
  team_overdue?: Task[]
  handovers?: any[]
}

export default function TodayPage() {
  const me = useMe()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['today'], queryFn: () => get<Today>('/today'), refetchInterval: 60_000 })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['today'] })
    qc.invalidateQueries({ queryKey: ['tasks'] })
    qc.invalidateQueries({ queryKey: ['alerts-count'] })
  }
  const hour = new Date().getHours()
  const greet = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  const d = q.data

  const section = (title: string, items: Task[] | undefined, empty: string, showOwner = false) => (
    <Card title={`${title}${items?.length ? ` (${items.length})` : ''}`} pad={false}>
      {items?.length ? items.map((t) => <TaskRow key={t.id} task={t} onChanged={refresh} showOwner={showOwner} />) : <Empty text={empty} />}
    </Card>
  )

  return (
    <>
      <PageHead title={`${greet}, ${me.user.first_name || me.membership.name}`} sub={new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })} />
      {q.isLoading || !d ? (
        <Spinner />
      ) : (
        <>
          <div className="grid tiles" style={{ marginBottom: 16 }}>
            <div className={`tile ${d.overdue.length ? 'dark' : ''}`}>
              <div className="k">Overdue</div>
              <div className="v">{d.overdue.length}</div>
              <div className="s">follow-ups and tasks</div>
            </div>
            <div className="tile">
              <div className="k">Due in 24 hours</div>
              <div className="v">{d.due_today.length}</div>
            </div>
            <div className="tile">
              <div className="k">Blocked</div>
              <div className="v">{d.blocked.length}</div>
            </div>
            <div className="tile">
              <div className="k">Open alerts</div>
              <div className="v">{d.alerts.length}</div>
            </div>
            <div className="tile">
              <div className="k">Completed today</div>
              <div className="v">{d.completed_today}</div>
            </div>
          </div>
          <div className="grid side">
            <div className="stack">
              {section('Overdue', d.overdue, 'Nothing overdue. Nice work.')}
              {section('Due in the next 24 hours', d.due_today, 'Nothing due in the next 24 hours.')}
              {d.blocked.length > 0 && section('Blocked', d.blocked, '')}
              {section('Coming up this week', d.upcoming, 'Nothing else scheduled this week.')}
              {d.team_overdue && section('Team: overdue work', d.team_overdue, 'No overdue work in your team.', true)}
            </div>
            <div className="stack">
              {d.handovers && (
                <Card title="Handovers waiting" pad={false}>
                  {d.handovers.length ? (
                    d.handovers.map((h) => (
                      <Link key={h.id} to={`/handovers?focus=${h.id}`} className="task" style={{ display: 'flex' }}>
                        <div style={{ flex: 1 }}>
                          <div className="ttl">{h.client_name}</div>
                          <div className="meta">
                            {h.opportunity.title} · promised {fmtDate(h.promised_end)}
                          </div>
                        </div>
                        <StatusBadge value={h.status} labelText={h.status_label} />
                      </Link>
                    ))
                  ) : (
                    <Empty text="No handovers waiting." />
                  )}
                </Card>
              )}
              <Card title="My alerts" pad={false} actions={<Link to="/alerts" className="btn sm ghost">All alerts</Link>}>
                <AlertList alerts={d.alerts} onChanged={refresh} compact />
              </Card>
              <Card title="Signed in as">
                <Person m={{ name: me.membership.name, role: me.membership.role }} sub />
              </Card>
            </div>
          </div>
        </>
      )}
    </>
  )
}
