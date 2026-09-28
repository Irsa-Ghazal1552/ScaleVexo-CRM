import type { ReactNode } from 'react'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import { ToastProvider } from '../components/ui'
import { AuthProvider, useAuth } from '../lib/auth'

/** Like App: pages render only after /auth/me has answered. */
function WhenAuthLoaded({ children }: { children: ReactNode }) {
  return useAuth().loading ? null : <>{children}</>
}

/** Renders UI with the app's providers. `routes` adds pages the UI may navigate to. */
export function renderApp(ui: ReactNode, { path = '/', at = path, routes = {} as Record<string, ReactNode> } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[at]}>
        <ToastProvider>
          <AuthProvider>
            <WhenAuthLoaded>
              <Routes>
                <Route path={path} element={ui} />
                {Object.entries(routes).map(([p, el]) => (
                  <Route key={p} path={p} element={el} />
                ))}
              </Routes>
            </WhenAuthLoaded>
          </AuthProvider>
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
