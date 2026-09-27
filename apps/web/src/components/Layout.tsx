import { FormEvent, ReactNode, useEffect, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart3, Bell, Briefcase, CalendarCheck, ClipboardList, FolderKanban, Handshake, LifeBuoy, LogOut, Menu, Search,
  Settings, Target, Users, UserSquare,
} from 'lucide-react'
import { get } from '../lib/api'
import { useAuth, useMe } from '../lib/auth'
import { ROLE_LABELS } from '../lib/format'
import { Avatar } from './ui'

function Clock({ tz }: { tz: string }) {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000)
    return () => clearInterval(t)
  }, [])
  let text = ''
  try {
    text = now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', timeZone: tz })
  } catch {
    text = now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  }
  return <span className="clock" title={`Workspace time (${tz})`}>{text}</span>
}

export default function Layout({ children }: { children: ReactNode }) {
  const me = useMe()
  const { logout } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const caps = me.capabilities
  const alerts = useQuery({ queryKey: ['alerts-count'], queryFn: () => get<{ open: number; critical: number }>('/alerts/count'), refetchInterval: 60_000 })

  useEffect(() => setOpen(false), [loc.pathname])

  const item = (to: string, icon: ReactNode, text: string, count?: number) => (
    <NavLink to={to} end={to === '/'} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
      {icon}
      <span>{text}</span>
      {!!count && <span className="count">{count}</span>}
    </NavLink>
  )

  const onSearch = (e: FormEvent) => {
    e.preventDefault()
    if (!search.trim()) return
    const target = caps.sales ? '/leads' : caps.delivery ? '/clients' : '/tickets'
    nav(`${target}?q=${encodeURIComponent(search.trim())}`)
  }

  return (
    <div className="shell">
      <aside className={`sidebar ${open ? 'open' : ''}`}>
        <div className="brand">
          <span className="brand-mark">S</span>
          <span>{me.workspace.name || 'ScaleVexo'} CRM</span>
        </div>
        <nav aria-label="Main">
          {item('/', <CalendarCheck size={18} />, 'Today')}
          {caps.sales && (
            <>
              <div className="nav-section">Sales</div>
              {item('/leads', <Target size={18} />, 'Leads')}
              {item('/deals', <Handshake size={18} />, 'Deals')}
            </>
          )}
          <div className="nav-section">Delivery</div>
          {item('/clients', <UserSquare size={18} />, 'Clients')}
          {(caps.delivery || caps.sales_manage) && item('/handovers', <ClipboardList size={18} />, 'Handovers')}
          {item('/projects', <FolderKanban size={18} />, 'Projects')}
          {item('/tickets', <LifeBuoy size={18} />, 'Tickets')}
          <div className="nav-section">Company</div>
          {item('/team', <Users size={18} />, 'Team')}
          {caps.reports && item('/reports', <BarChart3 size={18} />, 'Reports')}
          {item('/alerts', <Bell size={18} />, 'Alerts', alerts.data?.open)}
          {item('/settings', <Settings size={18} />, 'Settings')}
        </nav>
        <div className="me">
          <Avatar name={me.membership.name} />
          <div className="who">
            <b>{me.membership.name}</b>
            <span>{ROLE_LABELS[me.membership.role]}</span>
          </div>
          <button className="icon-btn" onClick={logout} title="Sign out" aria-label="Sign out">
            <LogOut size={17} />
          </button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <button className="icon-btn menu-toggle" onClick={() => setOpen(!open)} aria-label="Menu">
            <Menu size={20} />
          </button>
          <form className="search" onSubmit={onSearch} role="search">
            <Search size={16} />
            <input placeholder="Search leads, companies, clients…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search" />
          </form>
          <div className="spacer" />
          <Clock tz={me.workspace.timezone} />
          <button className="icon-btn bell" onClick={() => nav('/alerts')} aria-label="Alerts" title="Alerts">
            <Bell size={20} />
            {!!alerts.data?.open && <span className={`dot ${alerts.data.critical ? 'crit' : ''}`}>{alerts.data.open}</span>}
          </button>
          <button className="icon-btn" onClick={() => nav('/settings?tab=security')} title="My account" aria-label="My account">
            <Briefcase size={19} />
          </button>
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  )
}
