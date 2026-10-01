export type AuthUser = {
  id: string
  email: string
}

export type AuthResponse = {
  token: string
  token_type: string
  user: AuthUser
}

export type RegionOption = {
  region: string
  endpoint?: string
  opt_in_status?: string
}

export type ProgressEvent = {
  analysis_id: string
  message: string
  percent: number
  status: string
}

export type AnalysisIssue = {
  id: string
  title: string
  severity: 'high' | 'medium' | 'low' | string
  category?: string
  issue_type?: string
  resource_name?: string
  resource_ids?: string[]
  description: string
  recommendation: string
  estimated_monthly_savings_usd?: number | null
}

export type EstimatedSavings = {
  currency?: string
  monthly_low?: number | null
  monthly_high?: number | null
  annual_low?: number | null
  annual_high?: number | null
  notes?: string
}

export type FixCommand = {
  issue_id?: string
  description?: string
  command: string
  warning?: string
}

export type GeminiAnalysis = {
  summary: string
  issues: AnalysisIssue[]
  estimated_savings: EstimatedSavings
  fix_commands: FixCommand[]
  model?: string
  disclaimer?: string
}

export type ScannedResource = {
  resource_id?: string
  resource_name?: string
  service?: string
  resource_type?: string
}

export type AnalysisResult = {
  analysis_id: string
  region: string
  account_id?: string
  scanned_at?: string
  resource_count?: number
  counts_by_type?: Record<string, number>
  partial_errors?: Array<{ service?: string; code?: string; message?: string }>
  resources?: ScannedResource[]
  analysis?: GeminiAnalysis
}

export type HistoryItem = {
  id: string
  user_id: string
  region: string
  resources_scanned: number
  issues_found: number
  estimated_savings: string | null
  analysis_result: AnalysisResult | null
  status: string
  created_at: string | null
}
