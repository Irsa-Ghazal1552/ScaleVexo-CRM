import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { useStageMove } from '../pages/Deals'
import { renderApp } from './render'
import { recorder, server } from './server'

const DEAL = { id: 'd-1', title: 'Northwind website', stage: 'qualified', version: 4, scope_reference: '' }

function Harness({ deal, onDone }: { deal: any; onDone: () => void }) {
  const { move, dialog } = useStageMove(onDone)
  return (
    <>
      {['proposal', 'lost', 'won', 'negotiation'].map((s) => (
        <button key={s} onClick={() => move(deal, s)}>{`to ${s}`}</button>
      ))}
      {dialog}
    </>
  )
}

function stageEndpoint() {
  const rec = recorder()
  server.use(http.post('/api/opportunities/d-1/stage', async ({ request }) => {
    await rec.push(request)
    return HttpResponse.json({ ...DEAL })
  }))
  return rec
}

describe('moving a deal between stages', () => {
  it('asks for the scope reference before Proposal and sends it with the version', async () => {
    const rec = stageEndpoint()
    const onDone = vi.fn()
    renderApp(<Harness deal={DEAL} onDone={onDone} />)
    await userEvent.click(await screen.findByRole('button', { name: 'to proposal' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByRole('heading', { name: 'Move to Proposal' })).toBeInTheDocument()

    await userEvent.click(within(dialog).getByRole('button', { name: 'Move' }))
    expect(within(dialog).getByText('Please fill in the required fields.')).toBeInTheDocument()
    expect(rec.calls).toHaveLength(0)

    await userEvent.type(within(dialog).getByLabelText(/Scope \/ proposal reference/), 'Proposal SVX-P-0142')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Move' }))
    await vi.waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(rec.calls[0].body).toEqual({ scope_reference: 'Proposal SVX-P-0142', stage: 'proposal', version: 4 })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('requires a reason to close as lost', async () => {
    const rec = stageEndpoint()
    renderApp(<Harness deal={DEAL} onDone={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'to lost' }))
    const dialog = screen.getByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Move' }))
    expect(within(dialog).getByText('Required')).toBeInTheDocument()
    await userEvent.type(within(dialog).getByLabelText(/Why was it lost/), 'Chose a cheaper vendor')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Move' }))
    await vi.waitFor(() => expect(rec.calls[0]?.body).toEqual({ reason: 'Chose a cheaper vendor', stage: 'lost', version: 4 }))
  })

  it('moves straight away when the stage needs nothing extra', async () => {
    const rec = stageEndpoint()
    renderApp(<Harness deal={{ ...DEAL, stage: 'proposal', scope_reference: 'P-1' }} onDone={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'to negotiation' }))
    await vi.waitFor(() => expect(rec.calls[0]?.body).toEqual({ stage: 'negotiation', version: 4 }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows a stale-version conflict from the server', async () => {
    server.use(http.post('/api/opportunities/d-1/stage', () =>
      HttpResponse.json({ detail: 'This record was changed by someone else. Reload it and apply your change again.', code: 'stale_version' }, { status: 409 })))
    renderApp(<Harness deal={DEAL} onDone={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'to lost' }))
    const dialog = screen.getByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/Why was it lost/), 'x')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Move' }))
    expect(await within(dialog).findByText(/changed by someone else/)).toBeInTheDocument()
  })
})

describe('win-deal dialog', () => {
  it('explains that won is not paid and requires scope, reference, decision and a delivery owner', async () => {
    const rec = stageEndpoint()
    const onDone = vi.fn()
    renderApp(<Harness deal={{ ...DEAL, stage: 'negotiation', scope_reference: 'Proposal P-7' }} onDone={onDone} />)
    await userEvent.click(await screen.findByRole('button', { name: 'to won' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText(/Won does not mean paid/)).toBeInTheDocument()
    expect(within(dialog).getByLabelText(/Commercial reference/)).toHaveValue('Proposal P-7')

    await userEvent.click(within(dialog).getByRole('button', { name: 'Close as won' }))
    expect(within(dialog).getAllByText('Required')).toHaveLength(3) // scope, delivery owner, decision
    expect(rec.calls).toHaveLength(0)

    const owner = within(dialog).getByLabelText(/Delivery owner/)
    expect(within(owner).queryByText(/Rabia Muneeb/)).not.toBeInTheDocument() // sales reps are not offered
    await userEvent.type(within(dialog).getByLabelText(/Accepted scope/), '5-page site with booking')
    await userEvent.selectOptions(owner, 'm-dm')
    await userEvent.type(within(dialog).getByLabelText(/Commercial decision/), 'CEO approved, 50% advance')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Close as won' }))
    await vi.waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(rec.calls[0].body).toMatchObject({
      stage: 'won', version: 4, scope: '5-page site with booking', commercial_reference: 'Proposal P-7',
      delivery_owner_id: 'm-dm', commercial_decision: 'CEO approved, 50% advance',
    })
  })

  it('shows the server field errors when the win is refused', async () => {
    server.use(http.post('/api/opportunities/d-1/stage', () => HttpResponse.json({
      detail: 'Closing as won needs accepted scope, a commercial decision and a delivery owner.', code: 'won_requirements',
      fields: { delivery_owner_id: ['The delivery owner must be on the delivery team'] },
    }, { status: 400 })))
    renderApp(<Harness deal={{ ...DEAL, scope_reference: 'P' }} onDone={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'to won' }))
    const dialog = screen.getByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/Accepted scope/), 's')
    await userEvent.selectOptions(within(dialog).getByLabelText(/Delivery owner/), 'm-dm')
    await userEvent.type(within(dialog).getByLabelText(/Commercial decision/), 'd')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Close as won' }))
    expect(await within(dialog).findByText('The delivery owner must be on the delivery team')).toBeInTheDocument()
    expect(within(dialog).getByText(/Closing as won needs/)).toBeInTheDocument()
  })
})
