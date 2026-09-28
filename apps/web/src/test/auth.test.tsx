import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { LoginPage, MfaPanel } from '../pages/Auth'
import { renderApp } from './render'
import { me, recorder, server } from './server'

const anonymous = http.get('/api/auth/me', () => new HttpResponse(null, { status: 204 }))

async function signIn(email = 'sara@x.test', password = 'Correct-Pass-1') {
  await userEvent.type(await screen.findByLabelText('Work email'), email)
  await userEvent.type(screen.getByLabelText('Password'), password)
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
}

describe('login', () => {
  it('shows the server error for wrong credentials and stays on the form', async () => {
    server.use(
      anonymous,
      http.post('/api/auth/login', () =>
        HttpResponse.json({ detail: 'Email or password is incorrect.', code: 'invalid_credentials' }, { status: 400 })),
    )
    renderApp(<LoginPage />, { path: '/login' })
    await signIn('sara@x.test', 'wrong')
    expect(await screen.findByText('Email or password is incorrect.')).toBeInTheDocument()
    expect(screen.getByLabelText('Work email')).toHaveValue('sara@x.test')
  })

  it('signs in with CSRF and goes to the page the user asked for', async () => {
    const rec = recorder()
    let signedIn = false
    server.use(
      http.get('/api/auth/me', () => (signedIn ? HttpResponse.json(me()) : new HttpResponse(null, { status: 204 }))),
      http.post('/api/auth/login', async ({ request }) => {
        await rec.push(request)
        signedIn = true
        return HttpResponse.json(me())
      }),
    )
    renderApp(<LoginPage />, { path: '/login', at: '/login?next=/deals', routes: { '/deals': <h1>Deals page</h1> } })
    await signIn()
    expect(await screen.findByRole('heading', { name: 'Deals page' })).toBeInTheDocument()
    expect(rec.calls[0]).toEqual({ url: '/api/auth/login', body: { email: 'sara@x.test', password: 'Correct-Pass-1' }, csrf: 'test-token' })
  })

  it('asks for the MFA code when the account has MFA and rejects a wrong code', async () => {
    const rec = recorder()
    server.use(
      anonymous,
      http.post('/api/auth/login', () => HttpResponse.json({ mfa_required: true })),
      http.post('/api/auth/mfa-verify', async ({ request }) => {
        await rec.push(request)
        return rec.calls.length === 1
          ? HttpResponse.json({ detail: 'The verification code is not valid.', code: 'mfa_invalid' }, { status: 400 })
          : HttpResponse.json(me())
      }),
    )
    renderApp(<LoginPage />, { path: '/login', routes: { '/': <h1>Today</h1> } })
    await signIn()
    expect(await screen.findByRole('heading', { name: 'Verification code' })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Code'), '000000')
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))
    expect(await screen.findByText('The verification code is not valid.')).toBeInTheDocument()

    await userEvent.clear(screen.getByLabelText('Code'))
    await userEvent.type(screen.getByLabelText('Code'), '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))
    expect(await screen.findByRole('heading', { name: 'Today' })).toBeInTheDocument()
    expect(rec.calls.map((c) => c.body)).toEqual([{ code: '000000' }, { code: '123456' }])
  })
})

describe('MFA setup', () => {
  it('shows the setup key, then turns MFA on with the code from the app', async () => {
    const rec = recorder()
    server.use(
      http.post('/api/auth/mfa/setup', () => HttpResponse.json({ secret: 'JBSWY3DPEHPK3PXP', otpauth_uri: 'otpauth://totp/x' })),
      http.post('/api/auth/mfa/enable', async ({ request }) => {
        await rec.push(request)
        return HttpResponse.json(me('owner'))
      }),
    )
    let done = false
    renderApp(<MfaPanel onDone={() => (done = true)} />)
    await userEvent.click(await screen.findByRole('button', { name: /Set up authenticator app/ }))
    expect(await screen.findByText('JBSWY3DPEHPK3PXP')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/Enter the 6-digit code/), '654321')
    await userEvent.click(screen.getByRole('button', { name: 'Turn on MFA' }))
    await vi.waitFor(() => expect(done).toBe(true))
    expect(rec.calls[0].body).toEqual({ code: '654321' })
  })

  it('keeps the user on the step when the code is wrong', async () => {
    server.use(
      http.post('/api/auth/mfa/setup', () => HttpResponse.json({ secret: 'S', otpauth_uri: 'u' })),
      http.post('/api/auth/mfa/enable', () =>
        HttpResponse.json({ detail: 'The code does not match. Check your authenticator app and try again.', code: 'mfa_invalid' }, { status: 400 })),
    )
    renderApp(<MfaPanel />)
    await userEvent.click(await screen.findByRole('button', { name: /Set up authenticator app/ }))
    await userEvent.type(await screen.findByLabelText(/Enter the 6-digit code/), '111111')
    await userEvent.click(screen.getByRole('button', { name: 'Turn on MFA' }))
    expect(await screen.findByText(/The code does not match/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Turn on MFA' })).toBeInTheDocument()
  })
})
