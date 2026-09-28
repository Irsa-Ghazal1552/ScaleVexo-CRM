import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { TaskRow } from '../components/work'
import { renderApp } from './render'
import { recorder, server } from './server'

const TASK: any = {
  id: 't-1', title: 'Call Olivia', kind: 'follow_up', status: 'open', version: 2,
  due_at: new Date(Date.now() + 3600_000).toISOString(), original_due_at: new Date(Date.now() + 3600_000).toISOString(),
  overdue: false, reschedule_count: 0, reschedules: [], owner: { id: 'm-rep', name: 'Rabia Muneeb', role: 'sales_rep' },
  created_by_rule: '', context: null, outcome: '', blocked_reason: '',
}

function endpoint(action: string) {
  const rec = recorder()
  server.use(http.post(`/api/tasks/t-1/${action}`, async ({ request }) => {
    await rec.push(request)
    return HttpResponse.json({ ...TASK })
  }))
  return rec
}

describe('completing a task', () => {
  it('needs an outcome, then a next action or a reason to stop', async () => {
    const rec = endpoint('complete')
    const onChanged = vi.fn()
    renderApp(<TaskRow task={TASK} onChanged={onChanged} />)
    await userEvent.click(await screen.findByRole('button', { name: /Complete/ }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText(/schedule the next step or say why you are stopping/)).toBeInTheDocument()

    await userEvent.click(within(dialog).getByRole('button', { name: 'Complete' }))
    expect(within(dialog).getByText('Please fill in the required fields.')).toBeInTheDocument()

    await userEvent.type(within(dialog).getByLabelText(/Outcome/), 'Olivia will decide Friday')
    await userEvent.type(within(dialog).getByLabelText(/reason to stop/), 'Client went quiet for good')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Complete' }))
    await vi.waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(rec.calls[0].body).toMatchObject({ version: 2, outcome: 'Olivia will decide Friday', stop_reason: 'Client went quiet for good' })
  })

  it('schedules the next action instead of a stop reason', async () => {
    const rec = endpoint('complete')
    renderApp(<TaskRow task={TASK} onChanged={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: /Complete/ }))
    const dialog = screen.getByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/Outcome/), 'Sent the deck')
    await userEvent.type(within(dialog).getByLabelText('Next action'), 'Chase reply')
    expect(within(dialog).queryByLabelText(/reason to stop/)).not.toBeInTheDocument()
    expect(within(dialog).getByLabelText('Next action due')).not.toHaveValue('')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Complete' }))
    await vi.waitFor(() => expect(rec.calls).toHaveLength(1))
    const body = rec.calls[0].body
    expect(body).toMatchObject({ outcome: 'Sent the deck', next_action: 'Chase reply' })
    expect(new Date(body.next_action_due).getTime()).toBeGreaterThan(Date.now())
  })

  it('shows the server rule when the follow-up chain is missing', async () => {
    server.use(http.post('/api/tasks/t-1/complete', () => HttpResponse.json({
      detail: 'Schedule the next action or give a reason to stop following up.', code: 'next_action_required',
      fields: { next_action: ['Next action or stop reason required'] },
    }, { status: 400 })))
    renderApp(<TaskRow task={TASK} onChanged={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: /Complete/ }))
    const dialog = screen.getByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/Outcome/), 'x')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Complete' }))
    expect(await within(dialog).findByText('Next action or stop reason required')).toBeInTheDocument()
  })
})

describe('rescheduling a task', () => {
  it('requires a reason and tells the user the original deadline is kept', async () => {
    const rec = endpoint('reschedule')
    renderApp(<TaskRow task={TASK} onChanged={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: /Reschedule/ }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('The original deadline stays on record.')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(within(dialog).getByText('Required')).toBeInTheDocument()
    expect(rec.calls).toHaveLength(0)

    await userEvent.type(within(dialog).getByLabelText(/Reason/), 'Client travelling')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await vi.waitFor(() => expect(rec.calls).toHaveLength(1))
    expect(rec.calls[0].body).toMatchObject({ version: 2, reason: 'Client travelling' })
    expect(new Date(rec.calls[0].body.due_at).getTime()).toBeGreaterThan(new Date(TASK.due_at).getTime())
  })

  it('shows the reschedule history with the original deadline', async () => {
    const task = {
      ...TASK, reschedule_count: 2,
      reschedules: [{ id: 'r1', from_due: TASK.due_at, to_due: TASK.due_at, reason: 'Client asked', actor: { name: 'Rabia Muneeb' }, created_at: TASK.due_at }],
    }
    renderApp(<TaskRow task={task} onChanged={() => {}} />)
    await userEvent.click(await screen.findByText(/Rescheduled 2× · originally/))
    expect(screen.getByRole('heading', { name: 'Reschedule history' })).toBeInTheDocument()
    expect(screen.getByText(/Client asked/)).toBeInTheDocument()
  })
})
