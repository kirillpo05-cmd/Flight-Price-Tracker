import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import { getMe } from '../api/auth'
import type { User } from '../types'

interface AuthCtx {
  user: User | null
  token: string | null
  loading: boolean
  login: (token: string) => Promise<void>
  logout: () => void
  refresh: () => Promise<void>
}

const Ctx = createContext<AuthCtx | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('token'))
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchUser = async () => {
    try {
      const u = await getMe()
      setUser(u)
    } catch {
      setToken(null)
      setUser(null)
      localStorage.removeItem('token')
    }
  }

  useEffect(() => {
    if (token) {
      fetchUser().finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
  }, [])

  const login = async (t: string) => {
    localStorage.setItem('token', t)
    setToken(t)
    const u = await getMe()
    setUser(u)
  }

  const logout = () => {
    localStorage.removeItem('token')
    setToken(null)
    setUser(null)
    window.location.href = '/login'
  }

  const refresh = async () => {
    const u = await getMe()
    setUser(u)
  }

  return (
    <Ctx.Provider value={{ user, token, loading, login, logout, refresh }}>
      {children}
    </Ctx.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
