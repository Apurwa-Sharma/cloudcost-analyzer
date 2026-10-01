import { useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'

import { fetchHistoryItem } from '../lib/api'
import type { AnalysisIssue, AnalysisResult, FixCommand, GeminiAnalysis, ScannedResource } from '../types'

function severityClass(severity: string): string {
  const value = severity.toLowerCase()
  if (value === 'high') {
    return 'bg-red-500/20 text-red-400'
  }
  if (value === 'medium') {
    return 'bg-yellow-500/20 text-yellow-300'
  }
  return 'bg-green-500/20 text-green-400'
}

function issueTypeLabel(issue: AnalysisIssue): string {
  const raw = `${issue.issue_type || ''} ${issue.category || ''}`.toLowerCase()
  if (
    raw.includes('over-provision') ||
    raw.includes('over_provision') ||
    raw.includes('overprovision') ||
    raw.includes('instance_type')
  ) {
    return 'Over-provisioned'
  }
  if (raw.includes('unused') || raw.includes('idle')) {
    return 'Unused'
  }
  if (raw.includes('misconfig')) {
    return 'Misconfigured'
  }
  return 'Misconfigured'
}

function resourceNameForIssue(issue: AnalysisIssue, resources: ScannedResource[]): string {
  if (issue.resource_name) {
    return issue.resource_name
  }
  const ids = issue.resource_ids || []
  const match = resources.find(
    (resource) =>
      (resource.resource_id && ids.includes(resource.resource_id)) ||
      (resource.resource_name && ids.includes(resource.resource_name)),
  )
  if (match?.resource_name) {
    return match.resource_name
  }
  if (match?.resource_id) {
    return match.resource_id
  }
  return ids[0] || issue.title
}

function formatMonthlySavings(analysis: GeminiAnalysis | undefined): string {
  const savings = analysis?.estimated_savings
  const currency = savings?.currency || 'USD'
  const low = savings?.monthly_low
  const high = savings?.monthly_high
  if (low != null && high != null && low !== high) {
    return `${currency} ${low} – ${high}`
  }
  if (high != null) {
    return `${currency} ${high}`
  }
  if (low != null) {
    return `${currency} ${low}`
  }
  const fromIssues = (analysis?.issues || []).reduce((total, issue) => {
    const value = Number(issue.estimated_monthly_savings_usd)
    return Number.isFinite(value) ? total + value : total
  }, 0)
  if (fromIssues > 0) {
    return `${currency} ${fromIssues}`
  }
  return 'Not estimated'
}

function commandsForIssue(
  issue: AnalysisIssue,
  issues: AnalysisIssue[],
  commands: FixCommand[],
): FixCommand[] {
  const keyed = commands.filter((item) => item.issue_id && item.issue_id === issue.id)
  if (keyed.length > 0) {
    return keyed
  }
  if (commands.some((item) => item.issue_id)) {
    return []
  }
  const index = issues.findIndex((item) => item.id === issue.id)
  const fallback = index >= 0 ? commands[index] : undefined
  return fallback ? [fallback] : []
}

function CopyableCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    await navigator.clipboard.writeText(command)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Fix command</p>
        <button
          type="button"
          onClick={() => void copy()}
          className="shrink-0 rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-cyan-500 hover:text-cyan-300"
        >
          {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      <pre className="overflow-x-auto rounded-lg border border-slate-800 bg-black/50 p-3 font-mono text-xs leading-6 text-cyan-200">
        {command}
      </pre>
    </div>
  )
}

function ReportBody({ result }: { result: AnalysisResult }) {
  const analysis: GeminiAnalysis | undefined = result.analysis
  const issues = analysis?.issues || []
  const commands = analysis?.fix_commands || []
  const resources = result.resources || []
  const assigned = new Set(
    issues.flatMap((issue) => commandsForIssue(issue, issues, commands)),
  )
  const unmatchedCommands = commands.filter((item) => !assigned.has(item))

  return (
    <div className="space-y-8">
      <section className="rounded-2xl border border-slate-800 bg-night-900 p-6">
        <p className="text-xs uppercase tracking-wide text-slate-500">{result.region}</p>
        <h2 className="mt-2 text-xl font-semibold text-white">Report summary</h2>
        <div className="mt-5 grid gap-4 sm:grid-cols-3">
          <div className="rounded-xl border border-slate-800 bg-night-950 p-4">
            <p className="text-xs uppercase tracking-wide text-slate-500">Total resources scanned</p>
            <p className="mt-2 text-2xl font-semibold text-white">{result.resource_count ?? 0}</p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-night-950 p-4">
            <p className="text-xs uppercase tracking-wide text-slate-500">Total issues found</p>
            <p className="mt-2 text-2xl font-semibold text-white">{issues.length}</p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-night-950 p-4">
            <p className="text-xs uppercase tracking-wide text-slate-500">Estimated potential monthly savings</p>
            <p className="mt-2 text-2xl font-semibold text-cyan-300">{formatMonthlySavings(analysis)}</p>
          </div>
        </div>
        {analysis?.summary ? (
          <p className="mt-5 whitespace-pre-wrap text-sm leading-6 text-slate-300">{analysis.summary}</p>
        ) : null}
      </section>

      <section>
        <h2 className="mb-4 text-xl font-semibold text-white">Issues</h2>
        <div className="space-y-4">
          {issues.length === 0 ? (
            <p className="text-sm text-slate-400">No issues were reported.</p>
          ) : (
            issues.map((issue) => {
              const relatedCommands = commandsForIssue(issue, issues, commands)
              return (
                <article key={issue.id} className="rounded-2xl border border-slate-800 bg-night-900 p-5">
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    <h3 className="text-lg font-medium text-white">{resourceNameForIssue(issue, resources)}</h3>
                    <span className="rounded-full bg-slate-800 px-2.5 py-1 text-xs font-medium text-slate-300">
                      {issueTypeLabel(issue)}
                    </span>
                    <span className={`rounded-full px-2.5 py-1 text-xs font-semibold uppercase ${severityClass(issue.severity)}`}>
                      {issue.severity}
                    </span>
                  </div>
                  <p className="text-sm text-slate-300">{issue.description}</p>
                  <p className="mt-3 text-sm text-slate-400">
                    <span className="font-medium text-slate-200">Recommended fix: </span>
                    {issue.recommendation}
                  </p>
                  {relatedCommands.length > 0 ? (
                    <div className="mt-4 space-y-3">
                      {relatedCommands.map((item, index) => (
                        <CopyableCommand key={`${issue.id}-${index}`} command={item.command} />
                      ))}
                    </div>
                  ) : null}
                </article>
              )
            })
          )}
        </div>
      </section>

      {unmatchedCommands.length > 0 ? (
        <section>
          <h2 className="mb-4 text-xl font-semibold text-white">Additional fix commands</h2>
          <p className="mb-4 text-sm text-slate-400">
            These AWS CLI commands are recommendations only. Review them before running anything in your account.
          </p>
          <div className="space-y-3">
            {unmatchedCommands.map((item, index) => (
              <div key={`${item.command}-${index}`} className="rounded-2xl border border-slate-800 bg-night-900 p-5">
                {item.description ? <p className="mb-3 text-sm text-slate-300">{item.description}</p> : null}
                <CopyableCommand command={item.command} />
                {item.warning ? <p className="mt-2 text-xs text-yellow-300">{item.warning}</p> : null}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {analysis?.disclaimer ? <p className="text-xs text-slate-500">{analysis.disclaimer}</p> : null}
    </div>
  )
}

export default function Report() {
  const { id } = useParams()
  const location = useLocation()
  const stateResult = location.state as AnalysisResult | null
  const [result, setResult] = useState<AnalysisResult | null>(stateResult)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(!stateResult)

  useEffect(() => {
    if (stateResult || !id) {
      return
    }
    const reportId = id
    let cancelled = false
    async function load() {
      setLoading(true)
      setError('')
      try {
        const item = await fetchHistoryItem(reportId)
        if (!cancelled) {
          setResult(item.analysis_result)
          if (!item.analysis_result) {
            setError(`This analysis is ${item.status} and has no stored report yet.`)
          }
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unable to load report')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [id, stateResult])

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <div className="mb-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold text-white">Analysis report</h1>
          <p className="mt-1 text-sm text-slate-500">Gemini findings for this AWS scan</p>
        </div>
        <Link to="/history" className="text-sm text-cyan-400 hover:text-cyan-300">
          Back to history
        </Link>
      </div>
      {loading ? <p className="text-sm text-slate-400">Loading report…</p> : null}
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {result ? <ReportBody result={result} /> : null}
    </main>
  )
}
