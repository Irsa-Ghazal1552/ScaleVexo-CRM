export const ROLE_LABELS: Record<string, string> = {
  owner: 'CEO / Owner',
  admin: 'Administrator',
  sales_manager: 'Sales manager',
  sales_rep: 'Sales representative',
  delivery_manager: 'Delivery manager',
  delivery_employee: 'Delivery employee',
}

export const LEAD_STATUSES = [
  { value: 'new', label: 'New' },
  { value: 'assigned', label: 'Assigned' },
  { value: 'contacting', label: 'Contacting' },
  { value: 'qualified', label: 'Qualified' },
  { value: 'nurture', label: 'Nurture' },
  { value: 'disqualified', label: 'Disqualified' },
]

export const STAGES = [
  { value: 'discovery', label: 'Discovery' },
  { value: 'qualified', label: 'Qualified' },
  { value: 'proposal', label: 'Proposal' },
  { value: 'negotiation', label: 'Negotiation' },
  { value: 'won', label: 'Won' },
  { value: 'lost', label: 'Lost' },
]

export const ACTIVITY_KINDS = [
  { value: 'call', label: 'Call' },
  { value: 'email', label: 'Email' },
  { value: 'meeting', label: 'Meeting' },
  { value: 'linkedin', label: 'LinkedIn' },
  { value: 'note', label: 'Note' },
]

export const SEVERITIES = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'critical', label: 'Critical' },
]

export const CURRENCIES = ['USD', 'PKR', 'EUR', 'GBP', 'AED', 'SAR', 'CAD', 'AUD']

export function label(list: { value: string; label: string }[], value: string) {
  return list.find((x) => x.value === value)?.label || value
}

export function fmtDate(v?: string | null) {
  if (!v) return '—'
  const d = new Date(v.length === 10 ? v + 'T00:00:00' : v)
  if (isNaN(d.getTime())) return v
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

export function fmtDateTime(v?: string | null) {
  if (!v) return '—'
  const d = new Date(v)
  if (isNaN(d.getTime())) return v
  return d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export function relative(v?: string | null) {
  if (!v) return '—'
  const when = new Date(v)
  const diff = (when.getTime() - Date.now()) / 1000
  const abs = Math.abs(diff)
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
  if (abs < 60) return 'just now'
  if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour')
  // Count calendar days so "yesterday" really means the previous date, not "about 24 hours ago".
  const midnight = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const days = Math.round((midnight(when) - midnight(new Date())) / 86400000)
  if (Math.abs(days) < 7) return rtf.format(days, 'day')
  if (abs < 2629800) return rtf.format(Math.round(diff / 604800), 'week')
  return rtf.format(Math.round(diff / 2629800), 'month')
}

/** Operating-cost amounts (the API keeps 4-6 decimals for AI spend). */
export function usd(value?: string | number | null) {
  const n = Number(value || 0)
  if (n > 0 && n < 0.01) return '< $0.01'
  return '$' + n.toFixed(2)
}

export function money(value?: string | number | null, currency?: string) {
  if (value === null || value === undefined || value === '') return 'Value unknown'
  const n = Number(value)
  if (isNaN(n)) return String(value)
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency: currency || 'USD', maximumFractionDigits: 0 }).format(n)
  } catch {
    return `${currency || ''} ${n.toLocaleString()}`
  }
}

export function toLocalInput(v?: string | null) {
  // ISO -> value for <input type="datetime-local">
  if (!v) return ''
  const d = new Date(v)
  const pad = (x: number) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function inHours(h: number) {
  return toLocalInput(new Date(Date.now() + h * 3600 * 1000).toISOString())
}

/** datetime-local values carry no zone; send them as absolute ISO strings from the browser's zone. */
export function localToIso(v?: string) {
  if (!v) return v
  if (v.length === 10) return v
  const d = new Date(v)
  return isNaN(d.getTime()) ? v : d.toISOString()
}

export function initials(name?: string) {
  if (!name) return '?'
  const parts = name.replace(/[^\p{L}\s]/gu, ' ').trim().split(/\s+/)
  return ((parts[0]?.[0] || '') + (parts[1]?.[0] || '')).toUpperCase() || '?'
}

export function entityPath(type: string, id: string) {
  switch (type) {
    case 'lead':
      return `/leads/${id}`
    case 'opportunity':
      return `/deals/${id}`
    case 'client':
      return `/clients/${id}`
    case 'project':
      return `/projects/${id}`
    case 'ticket':
      return `/tickets/${id}`
    case 'handover':
      return `/handovers?focus=${id}`
    case 'task':
      return `/`
    case 'milestone':
      return `/projects`
    case 'correction':
      return `/team?tab=corrections`
    default:
      return '/'
  }
}
