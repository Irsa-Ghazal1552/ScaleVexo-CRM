import { createContext, ReactNode, useContext } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, get, post } from './api'

export type Me = {
  user: { id: number; email: string; first_name: string; last_name: string }
  membership: { id: string; name: string; role: string; role_label: string; title: string; mfa_enabled: boolean }
  workspace: { id: string; name: string; timezone: string; default_currency: string; work_start: string; work_end: string; work_days: string }
  mfa_setup_required: boolean
  capabilities: {
    sales: boolean
    sales_manage: boolean
    delivery: boolean
    delivery_manage: boolean
    manager: boolean
    configure: boolean
    commercials: boolean
    receipts: boolean
    export: boolean
    reports: boolean
  }
  roles: { value: string; label: string }[]
}

type Ctx = { me: Me | null; loading: boolean; refresh: () => Promise<any>; logout: () => Promise<void> }
const AuthCtx = createContext<Ctx>({ me: null, loading: true, refresh: async () => {}, logout: async () => {} })

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        return await get<Me>('/auth/me')
      } catch (e) {
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return null
        throw e
      }
    },
    retry: false,
    staleTime: 5 * 60_000,
  })
  const value: Ctx = {
    me: q.data ?? null,
    loading: q.isLoading,
    refresh: () => q.refetch(),
    logout: async () => {
      try {
        await post('/auth/logout')
      } finally {
        qc.clear()
        window.location.href = '/login'
      }
    },
  }
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>
}

export const useAuth = () => useContext(AuthCtx)
export const useMe = () => useContext(AuthCtx).me as Me
