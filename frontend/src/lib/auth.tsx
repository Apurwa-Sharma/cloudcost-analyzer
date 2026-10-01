import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'

import {
  clearSession,
  getStoredEmail,
  getToken,
  login as loginRequest,
  signup as signupRequest,
  storeSession,
} from './api'

type AuthContextValue = {
  token: string | null
  email: string | null
  login: (email: string, password: string) => Promise<void>
  signup: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => getToken())
  const [email, setEmail] = useState<string | null>(() => getStoredEmail())

  const value = useMemo<AuthContextValue>(
    () => ({
      token,
      email,
      async login(nextEmail, password) {
        const result = await loginRequest(nextEmail, password)
        storeSession(result.token, result.user.email)
        setToken(result.token)
        setEmail(result.user.email)
      },
      async signup(nextEmail, password) {
        const result = await signupRequest(nextEmail, password)
        storeSession(result.token, result.user.email)
        setToken(result.token)
        setEmail(result.user.email)
      },
      logout() {
        clearSession()
        setToken(null)
        setEmail(null)
      },
    }),
    [token, email],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}
