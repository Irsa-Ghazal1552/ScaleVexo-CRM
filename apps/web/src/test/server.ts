import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

export const MEMBERS = [
  { id: 'm-rep', name: 'Rabia Muneeb', email: 'rabia@x.test', role: 'sales_rep', status: 'active', title: '' },
  { id: 'm-mgr', name: 'Sara Khan', email: 'sara@x.test', role: 'sales_manager', status: 'active', title: '' },
  { id: 'm-dm', name: 'Hamza Iqbal', email: 'hamza@x.test', role: 'delivery_manager', status: 'active', title: '' },
]

export function me(role = 'sales_manager') {
  const manager = ['owner', 'sales_manager', 'delivery_manager'].includes(role)
  return {
    user: { id: 1, email: 'sara@x.test', first_name: 'Sara', last_name: 'Khan' },
    membership: { id: 'm-mgr', name: 'Sara Khan', role, role_label: role, title: '', mfa_enabled: false },
    workspace: { id: 'w1', name: 'ScaleVexo', timezone: 'UTC', default_currency: 'USD', work_start: '09:00', work_end: '18:00', work_days: '0,1,2,3,4' },
    mfa_setup_required: false,
    capabilities: {
      sales: ['owner', 'sales_manager', 'sales_rep'].includes(role),
      sales_manage: ['owner', 'sales_manager'].includes(role),
      delivery: ['owner', 'delivery_manager', 'delivery_employee'].includes(role),
      delivery_manage: ['owner', 'delivery_manager'].includes(role),
      manager,
      configure: ['owner', 'admin'].includes(role),
      commercials: role !== 'delivery_employee',
      receipts: role === 'owner',
      export: role === 'owner',
      reports: manager,
    },
    roles: [],
  }
}

/** Default handlers; each test adds the ones it is about with server.use(). */
export const server = setupServer(
  http.get('/api/auth/csrf', () => HttpResponse.json({ ok: true })),
  http.get('/api/auth/me', () => HttpResponse.json(me())),
  http.get('/api/team/members', () => HttpResponse.json(MEMBERS)),
)

/** Captures request bodies so tests can assert what was sent. */
export function recorder() {
  const calls: { url: string; body: any; csrf: string | null }[] = []
  return {
    calls,
    async push(request: Request) {
      calls.push({ url: new URL(request.url).pathname, body: await request.clone().json().catch(() => null), csrf: request.headers.get('X-CSRFToken') })
    },
  }
}
