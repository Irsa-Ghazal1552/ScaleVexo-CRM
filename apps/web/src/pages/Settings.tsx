import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Play, Upload } from 'lucide-react'
import { api, download, get, patch, post, put } from '../lib/api'
import { useAuth, useMe } from '../lib/auth'
import { fmtDateTime, ROLE_LABELS, usd } from '../lib/format'
import { Badge, Card, Empty, errorText, FieldInput, FormModal, PageHead, Pager, Spinner, Tabs, useMembers, useToast } from '../components/ui'
import { MfaPanel } from './Auth'

export default function SettingsPage() {
  const me = useMe()
  const [params, setParams] = useSearchParams()
  const cfg = me.capabilities.configure
  const tabs = [
    ...(cfg ? [{ value: 'workspace', label: 'Workspace' }] : []),
    { value: 'rules', label: 'Rules & alerts' },
    { value: 'ai', label: 'AI' },
    ...(me.capabilities.sales_manage ? [{ value: 'import', label: 'Import' }] : []),
    { value: 'templates', label: 'Project templates' },
    ...(cfg ? [{ value: 'audit', label: 'Audit log' }] : []),
    ...(me.capabilities.export || me.capabilities.sales_manage ? [{ value: 'export', label: 'Export & backup' }] : []),
    { value: 'security', label: 'My account' },
  ]
  const tab = params.get('tab') || tabs[0].value
  return (
    <>
      <PageHead title="Settings" />
      <Tabs tabs={tabs} value={tab} onChange={(v) => setParams({ tab: v })} />
      {tab === 'workspace' && <WorkspaceTab />}
      {tab === 'rules' && <RulesTab />}
      {tab === 'ai' && <AITab />}
      {tab === 'import' && <ImportTab />}
      {tab === 'templates' && <TemplatesTab />}
      {tab === 'audit' && <AuditTab />}
      {tab === 'export' && <ExportTab />}
      {tab === 'security' && <SecurityTab />}
    </>
  )
}

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function WorkspaceTab() {
  const { refresh } = useAuth()
  const toast = useToast()
  const q = useQuery({ queryKey: ['workspace'], queryFn: () => get<any>('/settings/workspace') })
  const [form, setForm] = useState<any>(null)
  useEffect(() => {
    if (q.data) setForm(q.data)
  }, [q.data])
  if (!form) return <Spinner />
  const days = new Set(String(form.work_days).split(',').filter(Boolean))
  const save = () =>
    patch('/settings/workspace', { ...form, work_start: form.work_start.slice(0, 5), work_end: form.work_end.slice(0, 5) })
      .then(() => {
        toast('Workspace saved')
        refresh()
      })
      .catch((e) => toast(errorText(e), 'error'))
  return (
    <Card title="Workspace and working calendar">
      <div className="row">
        <div className="field">
          <label htmlFor="ws-name">Workspace name</label>
          <input id="ws-name" className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="ws-tz">Time zone</label>
          <input id="ws-tz" className="input" value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} />
          <span className="hint">e.g. Asia/Karachi, America/New_York</span>
        </div>
        <div className="field">
          <label htmlFor="ws-currency">Default currency</label>
          <input id="ws-currency" className="input" value={form.default_currency} onChange={(e) => setForm({ ...form, default_currency: e.target.value.toUpperCase() })} maxLength={3} />
        </div>
      </div>
      <div className="row">
        <div className="field">
          <label htmlFor="ws-start">Working hours start</label>
          <input id="ws-start" className="input" type="time" value={form.work_start.slice(0, 5)} onChange={(e) => setForm({ ...form, work_start: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="ws-end">Working hours end</label>
          <input id="ws-end" className="input" type="time" value={form.work_end.slice(0, 5)} onChange={(e) => setForm({ ...form, work_end: e.target.value })} />
        </div>
        <div className="field">
          <span className="label" id="ws-days">Working days</span>
          <div className="flex wrap" role="group" aria-labelledby="ws-days">
            {DAYS.map((d, i) => (
              <label key={d} className="check">
                <input
                  type="checkbox"
                  checked={days.has(String(i))}
                  onChange={(e) => {
                    const next = new Set(days)
                    e.target.checked ? next.add(String(i)) : next.delete(String(i))
                    setForm({ ...form, work_days: Array.from(next).sort().join(',') })
                  }}
                />
                {d}
              </label>
            ))}
          </div>
        </div>
      </div>
      <p className="muted small">Rule timings (e.g. "2 working hours") are counted in this calendar.</p>
      <button className="btn primary" onClick={save}>
        Save
      </button>
    </Card>
  )
}

function RulesTab() {
  const me = useMe()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['rules'], queryFn: () => get<any>('/rules') })
  const [editing, setEditing] = useState<any>(null)
  const refresh = () => qc.invalidateQueries({ queryKey: ['rules'] })
  const run = () =>
    post('/rules/run')
      .then(() => {
        toast('Rules evaluated')
        refresh()
        qc.invalidateQueries({ queryKey: ['alerts-count'] })
      })
      .catch((e) => toast(errorText(e), 'error'))
  if (q.isLoading) return <Spinner />
  const worker = q.data.worker
  return (
    <div className="stack">
      <div className="notice flex wrap">
        <span>
          The background worker evaluates these rules every minute. Last run: <b>{worker.last_run_at ? fmtDateTime(worker.last_run_at) : 'never'}</b>. External sending is off in Release 1 -
          rules create tasks and in-app alerts only.
        </span>
        {me.capabilities.manager || me.capabilities.configure ? (
          <button className="btn sm right" onClick={run}>
            <Play size={13} /> Run now
          </button>
        ) : null}
      </div>
      {q.data.rules.map((r: any) => (
        <Card
          key={r.id}
          title={
            <span className="flex">
              <Badge tone="dark">{r.code}</Badge> {r.name} <span className="muted small">v{r.version}</span>
            </span>
          }
          actions={
            me.capabilities.configure ? (
              <>
                <label className="check small">
                  <input type="checkbox" checked={r.enabled} onChange={(e) => patch(`/rules/${r.id}`, { enabled: e.target.checked }).then(refresh)} />
                  {r.enabled ? 'Active' : 'Paused'}
                </label>
                {Object.keys(r.params).length > 0 && (
                  <button className="btn sm" onClick={() => setEditing(r)}>
                    Edit settings
                  </button>
                )}
              </>
            ) : (
              <Badge>{r.enabled ? 'Active' : 'Paused'}</Badge>
            )
          }
        >
          <dl className="kv">
            <dt>Trigger</dt>
            <dd>{r.trigger}</dd>
            <dt>Conditions</dt>
            <dd>{r.conditions}</dd>
            <dt>Action</dt>
            <dd>{r.action}</dd>
            <dt>Why</dt>
            <dd className="muted">{r.explanation}</dd>
            {Object.keys(r.params).length > 0 && (
              <>
                <dt>Settings</dt>
                <dd>
                  {Object.entries(r.params)
                    .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${k.endsWith('_role') ? ROLE_LABELS[v as string] || v : k === 'incident_owner_id' ? (v ? q.data.members.find((m: any) => m.id === v)?.name : 'not set') : v}`)
                    .join(' · ')}
                </dd>
              </>
            )}
            {worker.last_result?.[r.code] && (
              <>
                <dt>Last result</dt>
                <dd className="small muted">{JSON.stringify(worker.last_result[r.code])}</dd>
              </>
            )}
          </dl>
        </Card>
      ))}
      {editing && (
        <FormModal
          title={`${editing.code} settings`}
          fields={Object.keys(editing.params).map((k) =>
            k.endsWith('_role')
              ? { name: k, label: k.replace(/_/g, ' '), type: 'select' as const, options: me.roles }
              : k === 'incident_owner_id'
                ? { name: k, label: 'Incident owner', type: 'member' as const }
                : { name: k, label: k.replace(/_/g, ' '), type: 'number' as const },
          )}
          initial={editing.params}
          onClose={() => setEditing(null)}
          onSubmit={(v) => patch(`/rules/${editing.id}`, { params: v }).then(refresh)}
        />
      )}
    </div>
  )
}

function AITab() {
  const me = useMe()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['ai-settings'], queryFn: () => get<any>('/ai/settings') })
  const hist = useQuery({ queryKey: ['ai-history'], queryFn: () => get<any[]>('/ai/history'), enabled: me.capabilities.configure })
  const [form, setForm] = useState<any>(null)
  useEffect(() => {
    if (q.data) setForm(q.data)
  }, [q.data])
  if (!form) return <Spinner />
  const u = q.data.usage
  const save = () =>
    patch('/ai/settings', {
      enabled: form.enabled, provider: form.provider, model: form.model, max_output_tokens: form.max_output_tokens,
      input_cost_per_mtok: form.input_cost_per_mtok, output_cost_per_mtok: form.output_cost_per_mtok,
      ...(me.membership.role === 'owner' ? { monthly_budget_usd: form.monthly_budget_usd } : {}),
    })
      .then(() => {
        toast('AI settings saved')
        qc.invalidateQueries({ queryKey: ['ai-settings'] })
      })
      .catch((e) => toast(errorText(e), 'error'))
  return (
    <div className="stack">
      <div className="grid tiles">
        <div className="tile dark">
          <div className="k">Spent this month</div>
          <div className="v">{usd(u.spent_usd)}</div>
          <div className="s">of {usd(u.budget_usd)} limit</div>
        </div>
        <div className="tile">
          <div className="k">Remaining</div>
          <div className="v">{usd(u.remaining_usd)}</div>
        </div>
        <div className="tile">
          <div className="k">Requests</div>
          <div className="v">{u.requests}</div>
          <div className="s">{u.month}</div>
        </div>
        <div className="tile">
          <div className="k">Status</div>
          <div className="v" style={{ fontSize: 20 }}>{u.enabled ? 'On' : 'Off'}</div>
          <div className="s">{u.provider === 'mock' ? 'Offline test provider' : u.api_key_configured ? 'API key configured' : 'API key missing on server'}</div>
        </div>
      </div>
      <Card title="AI assistance (optional)">
        <div className="notice" style={{ marginBottom: 14 }}>
          AI only summarizes selected notes and drafts follow-ups for review. It never sends messages, changes stages, promises prices or judges employees. The CRM works fully with AI off. The
          monthly limit is enforced for the whole organisation.
        </div>
        {me.capabilities.configure ? (
          <>
            <label className="check" style={{ marginBottom: 12 }}>
              <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} /> AI assistance enabled
            </label>
            <div className="row">
              <FieldInput def={{ name: 'provider', label: 'Provider', type: 'select', options: form.providers }} value={form.provider} onChange={(v) => setForm({ ...form, provider: v })} />
              <FieldInput def={{ name: 'model', label: 'Model', hint: 'e.g. claude-haiku-4-5 (low cost)' }} value={form.model} onChange={(v) => setForm({ ...form, model: v })} />
            </div>
            <div className="row">
              <FieldInput
                def={{ name: 'monthly_budget_usd', label: 'Monthly budget (USD)', type: 'number', hint: me.membership.role === 'owner' ? undefined : 'Only the owner can change the budget' }}
                value={form.monthly_budget_usd}
                onChange={(v) => setForm({ ...form, monthly_budget_usd: v })}
              />
              <FieldInput def={{ name: 'input_cost_per_mtok', label: 'Input cost per 1M tokens (USD)', type: 'number' }} value={form.input_cost_per_mtok} onChange={(v) => setForm({ ...form, input_cost_per_mtok: v })} />
              <FieldInput def={{ name: 'output_cost_per_mtok', label: 'Output cost per 1M tokens (USD)', type: 'number' }} value={form.output_cost_per_mtok} onChange={(v) => setForm({ ...form, output_cost_per_mtok: v })} />
            </div>
            <p className="muted small">To use Claude, set ANTHROPIC_API_KEY in the server .env file, then choose "Anthropic Claude API". Check current prices before setting costs.</p>
            <button className="btn primary" onClick={save}>
              Save
            </button>
          </>
        ) : (
          <div className="muted">Ask an administrator to change AI settings.</div>
        )}
      </Card>
      {me.capabilities.configure && (
        <Card title="Recent AI requests" pad={false}>
          {!hist.data?.length ? (
            <Empty text="No AI requests yet." />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Feature</th>
                  <th>By</th>
                  <th>Status</th>
                  <th>Tokens</th>
                  <th>Cost</th>
                  <th>User decision</th>
                </tr>
              </thead>
              <tbody>
                {hist.data.map((r) => (
                  <tr key={r.id}>
                    <td>{fmtDateTime(r.created_at)}</td>
                    <td>{r.feature}</td>
                    <td>{r.requested_by}</td>
                    <td>
                      {r.status} {r.error && <div className="small muted">{r.error}</div>}
                    </td>
                    <td>
                      {r.input_tokens} / {r.output_tokens}
                    </td>
                    <td>${r.cost_usd}</td>
                    <td>{r.user_decision || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
    </div>
  )
}

function ImportTab() {
  const qc = useQueryClient()
  const toast = useToast()
  const members = useMembers()
  const history = useQuery({ queryKey: ['imports'], queryFn: () => get<any[]>('/imports') })
  const [batch, setBatch] = useState<any>(null)
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [owner, setOwner] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const upload = async (file: File) => {
    setErr('')
    setBusy(true)
    try {
      const form = new FormData()
      form.append('file', file)
      const b = await api('/imports', { method: 'POST', form })
      setBatch(b)
      setMapping(b.mapping || {})
      if (b.already_uploaded) toast(b.status === 'confirmed' ? 'This exact file was already imported - nothing will be duplicated.' : 'This file was uploaded before - continuing.')
    } catch (e) {
      setErr(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const confirm = async () => {
    setErr('')
    setBusy(true)
    try {
      const b = await post(`/imports/${batch.id}/confirm`, { mapping, default_owner_id: owner || null })
      setBatch({ ...batch, ...b })
      qc.invalidateQueries({ queryKey: ['imports'] })
      qc.invalidateQueries({ queryKey: ['leads'] })
      toast('Import finished')
    } catch (e) {
      setErr(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const targets: string[] = batch?.targets || []
  return (
    <div className="stack">
      <Card title="Import leads from a spreadsheet (CSV)">
        <ol className="muted" style={{ marginTop: 0, lineHeight: 1.7 }}>
          <li>In Excel or Google Sheets: File → Download / Save as → CSV.</li>
          <li>Upload it here, check the column matching, then confirm.</li>
          <li>Duplicates (same email or phone) and invalid rows are skipped and listed in an error file. Re-uploading the same file never creates duplicates.</li>
        </ol>
        {err && <div className="notice error" style={{ marginBottom: 10 }}>{err}</div>}
        <label className="btn primary">
          <Upload size={15} /> {busy ? 'Working…' : 'Choose CSV file'}
          <input type="file" accept=".csv,text/csv" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        </label>
      </Card>
      {batch && (
        <Card title={`${batch.file_name} · ${batch.row_count} rows`} actions={<Badge tone={batch.status === 'confirmed' ? 'dark' : ''}>{batch.status}</Badge>}>
          {batch.status === 'confirmed' ? (
            <div className="stack">
              <div className="grid tiles">
                {Object.entries(batch.counts).map(([k, v]: any) => (
                  <div className="tile" key={k}>
                    <div className="k">{k.replace(/_/g, ' ')}</div>
                    <div className="v">{v}</div>
                  </div>
                ))}
              </div>
              <div className="muted small">created + duplicates + invalid + skipped blank = total rows</div>
              {batch.has_errors && (
                <button className="btn" onClick={() => download(`/imports/${batch.id}/errors.csv`, `import-errors.csv`)}>
                  <Download size={15} /> Download error file
                </button>
              )}
            </div>
          ) : (
            <>
              <h4 style={{ marginBottom: 8 }}>Match your columns</h4>
              <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))' }}>
                {batch.headers.map((h: string, i: number) => (
                  <div className="field" key={h}>
                    <label htmlFor={`map-${i}`}>{h}</label>
                    <select id={`map-${i}`} className="select" value={mapping[h] || ''} onChange={(e) => setMapping({ ...mapping, [h]: e.target.value })}>
                      <option value="">Ignore this column</option>
                      {targets.map((t) => (
                        <option key={t} value={t}>
                          {t.replace(/_/g, ' ')}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
              <div className="field" style={{ maxWidth: 360 }}>
                <label htmlFor="import-owner">Owner for rows without an owner column</label>
                <select id="import-owner" className="select" value={owner} onChange={(e) => setOwner(e.target.value)}>
                  <option value="">Leave unassigned</option>
                  {(members.data || [])
                    .filter((m) => ['owner', 'sales_manager', 'sales_rep'].includes(m.role))
                    .map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                </select>
              </div>
              <h4 style={{ margin: '8px 0' }}>Preview (first rows)</h4>
              <div style={{ overflowX: 'auto' }}>
                <table className="table">
                  <thead>
                    <tr>
                      {batch.headers.map((h: string) => (
                        <th key={h}>
                          {h}
                          <div style={{ textTransform: 'none' }}>→ {mapping[h] || 'ignored'}</div>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {batch.preview.slice(0, 8).map((r: any, i: number) => (
                      <tr key={i}>
                        {batch.headers.map((h: string) => (
                          <td key={h}>{r[h]}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button className="btn primary" style={{ marginTop: 12 }} disabled={busy} onClick={confirm}>
                {busy ? 'Importing…' : `Import ${batch.row_count} rows`}
              </button>
            </>
          )}
        </Card>
      )}
      <Card title="Previous imports" pad={false}>
        {!history.data?.length ? (
          <Empty text="No imports yet." />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>File</th>
                <th>Status</th>
                <th>Result</th>
                <th>By</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {history.data.map((b) => (
                <tr key={b.id}>
                  <td>{b.file_name}</td>
                  <td>{b.status}</td>
                  <td className="small">{b.counts?.created !== undefined ? `${b.counts.created} created · ${b.counts.duplicates} duplicates · ${b.counts.invalid} invalid` : '—'}</td>
                  <td>{b.created_by?.name}</td>
                  <td>{fmtDateTime(b.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}

function TemplatesTab() {
  const me = useMe()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['templates'], queryFn: () => get<any[]>('/templates') })
  const [editing, setEditing] = useState<any>(null)
  const canEdit = me.capabilities.configure || me.capabilities.delivery_manage
  if (q.isLoading) return <Spinner />
  const toText = (ms: any[]) => ms.map((m) => `${m.title} | ${m.offset_days || 0} | ${(m.depends_on || []).map((d: number) => d + 1).join(',')}`).join('\n')
  const fromText = (t: string) =>
    t
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean)
      .map((l) => {
        const [title, offset, deps] = l.split('|').map((x) => (x || '').trim())
        return { title, offset_days: Number(offset) || 0, depends_on: (deps || '').split(',').filter(Boolean).map((d) => Number(d) - 1) }
      })
  return (
    <div className="stack">
      {canEdit && (
        <button className="btn primary" style={{ alignSelf: 'flex-start' }} onClick={() => setEditing({})}>
          + Template
        </button>
      )}
      {(q.data || []).map((t) => (
        <Card key={t.id} title={<span className="flex">{t.name} {t.is_default && <Badge tone="dark">Default for won deals</Badge>}</span>} actions={canEdit && <button className="btn sm" onClick={() => setEditing(t)}>Edit</button>}>
          <ol style={{ margin: 0, paddingLeft: 18 }}>
            {t.milestones.map((m: any, i: number) => (
              <li key={i}>
                {m.title} <span className="muted small">· day {m.offset_days} {m.depends_on?.length ? `· after #${m.depends_on.map((d: number) => d + 1).join(', #')}` : ''}</span>
              </li>
            ))}
          </ol>
        </Card>
      ))}
      {editing && (
        <FormModal
          title={editing.id ? 'Edit template' : 'New template'}
          fields={[
            { name: 'name', label: 'Name', required: true },
            { name: 'description', label: 'Description' },
            { name: 'milestones_text', label: 'Milestones - one per line: Title | days after start | depends on line numbers', type: 'textarea', required: true, placeholder: 'Kick-off | 3 |\nDesign | 10 | 1\nBuild | 25 | 2' },
            { name: 'is_default', label: 'Default', type: 'checkbox', hint: 'Use this template when a deal is won' },
          ]}
          initial={{ name: editing.name || '', description: editing.description || '', milestones_text: editing.milestones ? toText(editing.milestones) : '', is_default: !!editing.is_default }}
          onClose={() => setEditing(null)}
          onSubmit={(v) => {
            const body = { name: v.name, description: v.description, is_default: !!v.is_default, milestones: fromText(v.milestones_text) }
            return (editing.id ? put(`/templates/${editing.id}`, body) : post('/templates', body)).then(() => {
              toast('Template saved')
              qc.invalidateQueries({ queryKey: ['templates'] })
            })
          }}
        />
      )}
    </div>
  )
}

function AuditTab() {
  const [page, setPage] = useState(1)
  const q = useQuery({ queryKey: ['audit', page], queryFn: () => get<any>(`/audit?page=${page}`) })
  return (
    <div className="table-wrap">
      <div className="card-body muted small">Append-only history of important changes. Entries cannot be edited or deleted.</div>
      {q.isLoading ? (
        <Spinner />
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>When</th>
              <th>Who</th>
              <th>Action</th>
              <th>Summary</th>
            </tr>
          </thead>
          <tbody>
            {q.data.results.map((e: any) => (
              <tr key={e.id}>
                <td className="muted">{fmtDateTime(e.created_at)}</td>
                <td>{e.actor_name}</td>
                <td>
                  <code className="k">{e.action}</code>
                </td>
                <td>
                  {e.summary}
                  {e.data && Object.keys(e.data).length > 0 && (
                    <details className="small muted">
                      <summary>Details</summary>
                      <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(e.data, null, 1)}</pre>
                    </details>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {q.data && <Pager page={page} count={q.data.count} onPage={setPage} />}
    </div>
  )
}

function ExportTab() {
  const me = useMe()
  const toast = useToast()
  const dl = (path: string, name: string) => download(path, name).then(() => toast('Download started')).catch((e) => toast(errorText(e), 'error'))
  return (
    <div className="stack">
      {me.capabilities.export && (
        <Card title="Full workspace export">
          <p className="muted">All business records with stable IDs and relationships (JSON). Use it to move to another system or keep an independent copy.</p>
          <button className="btn primary" onClick={() => dl('/export/workspace.json', 'scalevexo-export.json')}>
            <Download size={15} /> Download workspace export
          </button>
        </Card>
      )}
      {me.capabilities.sales_manage && (
        <Card title="Leads spreadsheet">
          <p className="muted">CSV with formula protection, safe to open in Excel.</p>
          <button className="btn" onClick={() => dl('/export/leads.csv', 'leads.csv')}>
            <Download size={15} /> Download leads CSV
          </button>
        </Card>
      )}
      <Card title="Backups">
        <p className="muted" style={{ margin: 0 }}>
          Encrypted off-server database backups run on the server with <code className="k">infra/backup.sh</code> (restic, 7 daily / 4 weekly / 6 monthly). Restore with{' '}
          <code className="k">infra/restore.sh</code> and test a restore before live use. Audit history is included in every backup.
        </p>
      </Card>
    </div>
  )
}

function SecurityTab() {
  const me = useMe()
  const toast = useToast()
  const [pw, setPw] = useState(false)
  return (
    <div className="grid two">
      <Card title="Profile">
        <dl className="kv">
          <dt>Name</dt>
          <dd>{me.membership.name}</dd>
          <dt>Email</dt>
          <dd>{me.user.email}</dd>
          <dt>Role</dt>
          <dd>{me.membership.role_label}</dd>
        </dl>
        <button className="btn" style={{ marginTop: 12 }} onClick={() => setPw(true)}>
          Change password
        </button>
      </Card>
      <Card title="Multi-factor authentication">
        {me.membership.mfa_enabled ? (
          <div className="flex">
            <Badge tone="dark">On</Badge> <span className="muted">Your sign-in asks for a code from your authenticator app.</span>
          </div>
        ) : (
          <MfaPanel onDone={() => toast('MFA is on')} />
        )}
      </Card>
      {pw && (
        <FormModal
          title="Change password"
          fields={[
            { name: 'current_password', label: 'Current password', type: 'password', required: true },
            { name: 'new_password', label: 'New password (10+ characters)', type: 'password', required: true },
          ]}
          onClose={() => setPw(false)}
          onSubmit={(v) => post('/auth/password', v).then(() => toast('Password changed'))}
        />
      )}
    </div>
  )
}
