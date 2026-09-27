// One small API client for the whole app: same-origin session cookie + CSRF header.

export class ApiError extends Error {
  status: number
  code: string
  fields: Record<string, string[] | string>

  constructor(status: number, message: string, code = 'error', fields: Record<string, any> = {}) {
    super(message)
    this.status = status
    this.code = code
    this.fields = fields || {}
  }
}

function cookie(name: string): string {
  const match = document.cookie.split('; ').find((c) => c.startsWith(name + '='))
  return match ? decodeURIComponent(match.split('=')[1]) : ''
}

export async function ensureCsrf() {
  if (!cookie('csrftoken')) {
    await fetch('/api/auth/csrf', { credentials: 'same-origin' })
  }
}

type Options = { method?: string; body?: any; form?: FormData }

export async function api<T = any>(path: string, opts: Options = {}): Promise<T> {
  const method = opts.method || 'GET'
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (method !== 'GET') {
    await ensureCsrf()
    headers['X-CSRFToken'] = cookie('csrftoken')
  }
  let body: BodyInit | undefined
  if (opts.form) {
    body = opts.form
  } else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  let res: Response
  try {
    res = await fetch('/api' + path, { method, headers, body, credentials: 'same-origin' })
  } catch {
    throw new ApiError(0, 'Could not reach the server. Check your connection; your input has not been lost.', 'network')
  }
  if (res.status === 204) return null as T
  const text = await res.text()
  let data: any = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = { detail: text.slice(0, 300) }
  }
  if (!res.ok) {
    throw new ApiError(res.status, data?.detail || `Request failed (${res.status})`, data?.code, data?.fields)
  }
  return data as T
}

export const get = <T = any>(path: string) => api<T>(path)
export const post = <T = any>(path: string, body: any = {}) => api<T>(path, { method: 'POST', body })
export const patch = <T = any>(path: string, body: any = {}) => api<T>(path, { method: 'PATCH', body })
export const put = <T = any>(path: string, body: any = {}) => api<T>(path, { method: 'PUT', body })

export async function download(path: string, filename: string) {
  const res = await fetch('/api' + path, { credentials: 'same-origin' })
  if (!res.ok) {
    let msg = `Download failed (${res.status})`
    try {
      msg = (await res.json()).detail || msg
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg)
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function qs(params: Record<string, any>) {
  const p = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  })
  const s = p.toString()
  return s ? '?' + s : ''
}

export type Paged<T> = { count: number; next: string | null; previous: string | null; results: T[] }
export type MemberRef = { id: string; name: string; role: string } | null
