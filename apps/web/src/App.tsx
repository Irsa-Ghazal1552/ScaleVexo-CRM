import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router'
import Layout from './components/Layout'
import { Spinner } from './components/ui'
import { useAuth } from './lib/auth'
import { AcceptInvitePage, LoginPage, MfaSetupPage } from './pages/Auth'
import TodayPage from './pages/Today'
import { LeadDetailPage, LeadsPage } from './pages/Leads'
import { DealDetailPage, DealsPage } from './pages/Deals'
import { ClientDetailPage, ClientsPage, HandoversPage } from './pages/Clients'
import { ProjectDetailPage, ProjectsPage } from './pages/Projects'
import { TicketDetailPage, TicketsPage } from './pages/Tickets'
import TeamPage from './pages/Team'
import ReportsPage from './pages/Reports'
import AlertsPage from './pages/Alerts'
import SettingsPage from './pages/Settings'

export default function App() {
  const { me, loading } = useAuth()
  const loc = useLocation()

  if (loading) return <Spinner />

  if (!me) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/accept-invite/:token" element={<AcceptInvitePage />} />
        <Route path="*" element={<Navigate to={`/login?next=${encodeURIComponent(loc.pathname)}`} replace />} />
      </Routes>
    )
  }

  if (me.mfa_setup_required) {
    return (
      <Routes>
        <Route path="*" element={<MfaSetupPage forced />} />
      </Routes>
    )
  }

  // Same rules as the sidebar, so a typed URL cannot load a page whose API calls the role may not make.
  const caps = me.capabilities
  const only = (allowed: boolean, page: ReactNode) =>
    allowed ? page : <div className="empty">Your role does not have access to this page.</div>

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<TodayPage />} />
        <Route path="/leads" element={only(caps.sales, <LeadsPage />)} />
        <Route path="/leads/:id" element={only(caps.sales, <LeadDetailPage />)} />
        <Route path="/deals" element={only(caps.sales, <DealsPage />)} />
        <Route path="/deals/:id" element={<DealDetailPage />} />
        <Route path="/clients" element={<ClientsPage />} />
        <Route path="/clients/:id" element={<ClientDetailPage />} />
        <Route path="/handovers" element={only(caps.delivery || caps.sales_manage, <HandoversPage />)} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/projects/:id" element={<ProjectDetailPage />} />
        <Route path="/tickets" element={<TicketsPage />} />
        <Route path="/tickets/:id" element={<TicketDetailPage />} />
        <Route path="/team" element={<TeamPage />} />
        <Route path="/reports" element={only(caps.reports, <ReportsPage />)} />
        <Route path="/alerts" element={<AlertsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route path="/accept-invite/:token" element={<Navigate to="/" replace />} />
        <Route path="*" element={<div className="empty">Page not found.</div>} />
      </Routes>
    </Layout>
  )
}
