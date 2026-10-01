import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { fetchHistory } from '../lib/api'
import type { HistoryItem } from '../types'

function formatDate(value: string | null): string {
  if (!value) {
    return 'Unknown date'
  }
  return new Date(value).toLocaleString()
}

export default function History() {
  const navigate = useNavigate()
  const [items, setItems] = useState<HistoryItem[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError('')
      try {
        const data = await fetchHistory()
        if (!cancelled) {
          setItems(data.analyses)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unable to load history')
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
  }, [])

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-3xl font-semibold text-white">History</h1>
      <p className="mt-2 text-sm text-slate-400">Past AWS analyses stored in local PostgreSQL for your account.</p>

      {loading ? <p className="mt-6 text-sm text-slate-400">Loading history…</p> : null}
      {error ? <p className="mt-6 text-sm text-rose-400">{error}</p> : null}

      {!loading && !error && items.length === 0 ? (
        <p className="mt-8 text-sm text-slate-500">No analyses yet. Run one from the dashboard.</p>
      ) : null}

      <div className="mt-6 overflow-hidden rounded-2xl border border-slate-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-night-900 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">Region</th>
              <th className="px-4 py-3">Date</th>
              <th className="px-4 py-3">Issues</th>
              <th className="px-4 py-3">Estimated savings</th>
              <th className="px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr
                key={item.id}
                className="cursor-pointer border-t border-slate-800 bg-night-950/60 hover:bg-slate-900"
                onClick={() => navigate(`/report/${item.id}`)}
              >
                <td className="px-4 py-3 font-medium text-slate-100">{item.region}</td>
                <td className="px-4 py-3 text-slate-400">{formatDate(item.created_at)}</td>
                <td className="px-4 py-3 text-slate-200">{item.issues_found}</td>
                <td className="px-4 py-3 text-cyan-300">{item.estimated_savings || '—'}</td>
                <td className="px-4 py-3 capitalize text-slate-400">{item.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  )
}
