import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { LeadsPage } from '../pages/Leads'
import { renderApp } from './render'
import { recorder, server } from './server'

const DUPLICATE = 'A contact with this email or phone already exists: Olivia Carter · Brightpath. Open it or add the lead to it.'

beforeEach(() => {
  server.use(http.get('/api/leads', () => HttpResponse.json({ count: 0, next: null, previous: null, results: [] })))
})

async function openNewLead() {
  renderApp(<LeadsPage />, { path: '/leads', routes: { '/leads/:id': <h1>Lead detail</h1> } })
  await userEvent.click(await screen.findByRole('button', { name: 'Lead' }))
  return screen.getByRole('dialog')
}

describe('creating a lead', () => {
  it('warns about a duplicate contact and lets the user fix it without losing input', async () => {
    const rec = recorder()
    server.use(
      http.post('/api/leads', async ({ request }) => {
        await rec.push(request)
        if (rec.calls[rec.calls.length - 1].body.email === 'olivia@brightpath.test') {
          return HttpResponse.json({ detail: DUPLICATE, code: 'duplicate_contact', fields: { duplicates: ['c-1'] } }, { status: 400 })
        }
        return HttpResponse.json({ id: 'lead-9' }, { status: 201 })
      }),
    )
    const dialog = await openNewLead()
    await userEvent.type(within(dialog).getByLabelText('Contact name'), 'Olivia Carter')
    await userEvent.type(within(dialog).getByLabelText('Email'), 'olivia@brightpath.test')
    await userEvent.selectOptions(within(dialog).getByLabelText('Owner'), 'm-rep')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))

    expect((await within(dialog).findAllByText(DUPLICATE)).length).toBeGreaterThan(0)
    expect(within(dialog).getByLabelText('Contact name')).toHaveValue('Olivia Carter')
    expect(screen.queryByRole('heading', { name: 'Lead detail' })).not.toBeInTheDocument()

    await userEvent.clear(within(dialog).getByLabelText('Email'))
    await userEvent.type(within(dialog).getByLabelText('Email'), 'olivia.new@brightpath.test')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('heading', { name: 'Lead detail' })).toBeInTheDocument()
    expect(rec.calls[1].body).toMatchObject({ name: 'Olivia Carter', email: 'olivia.new@brightpath.test', owner_id: 'm-rep' })
  })

  it('shows field errors the server returns', async () => {
    server.use(
      http.post('/api/leads', () =>
        HttpResponse.json({ detail: 'Add one contact method (email, phone or LinkedIn) or a source reference.', code: 'business_rule',
          fields: { email: ['One contact method or source reference is required'] } }, { status: 400 })),
    )
    const dialog = await openNewLead()
    await userEvent.type(within(dialog).getByLabelText('Company'), 'No Contact Co')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(await within(dialog).findByText('One contact method or source reference is required')).toBeInTheDocument()
  })
})
