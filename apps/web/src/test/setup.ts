import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { server } from './server'

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
  // The app calls fetch('/api/...'). Node's fetch needs absolute URLs, so resolve them like a browser would.
  const mswFetch = globalThis.fetch
  globalThis.fetch = (input, init) =>
    mswFetch(typeof input === 'string' && input.startsWith('/') ? new URL(input, window.location.origin).href : input, init)
})

afterEach(() => {
  cleanup()
  server.resetHandlers()
  document.cookie = 'csrftoken=test-token'
})

afterAll(() => server.close())

document.cookie = 'csrftoken=test-token'
