import type { AnalysisResult, AuthResponse, HistoryItem, RegionOption } from '../types'

const TOKEN_KEY = 'ccd_token'
const EMAIL_KEY = 'ccd_email'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getStoredEmail(): string | null {
  return localStorage.getItem(EMAIL_KEY)
}

export function storeSession(token: string, email: string): void {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(EMAIL_KEY, email)
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(EMAIL_KEY)
}

export function apiErrorMessage(payload: unknown, fallback = 'Request failed'): string {
  if (!payload || typeof payload !== 'object') {
    return fallback
  }
  const detail = (payload as { detail?: unknown }).detail
  if (typeof detail === 'string') {
    return detail
  }
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as { message: unknown }).message)
  }
  return fallback
}

async function request<T>(path: string, options: RequestInit = {}, authRedirect = true): Promise<T> {
  const headers = new Headers(options.headers)
  if (!headers.has('Content-Type') && options.body) {
    headers.set('Content-Type', 'application/json')
  }
  const token = getToken()
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(path, { ...options, headers })
  const text = await response.text()
  const data = text ? (JSON.parse(text) as unknown) : null

  if (response.status === 401 && authRedirect && !path.startsWith('/api/auth/')) {
    clearSession()
    window.location.assign('/login')
    throw new Error('Not authenticated')
  }

  if (!response.ok) {
    throw new Error(apiErrorMessage(data, `Request failed (${response.status})`))
  }

  return data as T
}

export function signup(email: string, password: string): Promise<AuthResponse> {
  return request<AuthResponse>(
    '/api/auth/signup',
    { method: 'POST', body: JSON.stringify({ email, password }) },
    false,
  )
}

export function login(email: string, password: string): Promise<AuthResponse> {
  return request<AuthResponse>(
    '/api/auth/login',
    { method: 'POST', body: JSON.stringify({ email, password }) },
    false,
  )
}

export function fetchRegions(): Promise<{ regions: RegionOption[]; default_region: string }> {
  return request('/api/regions')
}

export function runAnalysis(region: string, analysisId: string): Promise<AnalysisResult> {
  return request('/api/analyze', {
    method: 'POST',
    body: JSON.stringify({ region, analysis_id: analysisId }),
  })
}

export function fetchHistory(): Promise<{ analyses: HistoryItem[] }> {
  return request('/api/history')
}

export function fetchHistoryItem(id: string): Promise<HistoryItem> {
  return request(`/api/history/${id}`)
}

export function progressSocketUrl(analysisId: string, token: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws/progress/${analysisId}?token=${encodeURIComponent(token)}`
}
