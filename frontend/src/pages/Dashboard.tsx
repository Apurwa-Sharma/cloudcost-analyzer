import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import ProgressTracker from '../components/ProgressTracker'
import { fetchRegions, getToken, progressSocketUrl, runAnalysis } from '../lib/api'
import type { ProgressEvent, RegionOption } from '../types'

export default function Dashboard() {
  const navigate = useNavigate()
  const [regions, setRegions] = useState<RegionOption[]>([])
  const [region, setRegion] = useState('')
  const [loadingRegions, setLoadingRegions] = useState(true)
  const [regionError, setRegionError] = useState('')
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState('')
  const [events, setEvents] = useState<ProgressEvent[]>([])

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoadingRegions(true)
      setRegionError('')
      try {
        const data = await fetchRegions()
        if (cancelled) {
          return
        }
        setRegions(data.regions)
        setRegion(data.default_region || data.regions[0]?.region || '')
      } catch (err) {
        if (!cancelled) {
          setRegionError(err instanceof Error ? err.message : 'Unable to load AWS regions')
        }
      } finally {
        if (!cancelled) {
          setLoadingRegions(false)
        }
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

  async function onRun() {
    const token = getToken()
    if (!token || !region) {
      return
    }
    const analysisId = crypto.randomUUID()
    setRunning(true)
    setRunError('')
    setEvents([])

    let socket: WebSocket | null = null
    try {
      socket = await new Promise<WebSocket>((resolve, reject) => {
        const ws = new WebSocket(progressSocketUrl(analysisId, token))
        ws.onmessage = (message) => {
          const payload = JSON.parse(message.data as string) as ProgressEvent
          setEvents((current) => [...current, payload])
        }
        ws.onopen = () => resolve(ws)
        ws.onerror = () => reject(new Error('Could not connect to live progress'))
      })

      const result = await runAnalysis(region, analysisId)
      navigate(`/report/${result.analysis_id}`, { state: result })
    } catch (err) {
      setRunError(err instanceof Error ? err.message : 'Analysis failed')
    } finally {
      socket?.close()
      setRunning(false)
    }
  }

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-3xl font-semibold text-white">Dashboard</h1>
      <p className="mt-2 max-w-2xl text-sm text-slate-400">
        Choose an AWS region, then run a read-only scan. Gemini analyzes the inventory and WebSocket events show live
        progress.
      </p>

      <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_1.1fr]">
        <section className="rounded-2xl border border-slate-800 bg-night-900 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">AWS region</h2>
          <label className="mt-4 block text-sm text-slate-300">
            Region
            <select
              value={region}
              disabled={loadingRegions || running}
              onChange={(event) => setRegion(event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-night-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
            >
              {regions.map((item) => (
                <option key={item.region} value={item.region}>
                  {item.region}
                </option>
              ))}
            </select>
          </label>
          {regionError ? <p className="mt-3 text-sm text-rose-400">{regionError}</p> : null}
          <button
            type="button"
            onClick={() => void onRun()}
            disabled={!region || running || Boolean(regionError)}
            className="mt-6 w-full rounded-lg bg-cyan-500 py-2.5 text-sm font-semibold text-night-950 hover:bg-cyan-400 disabled:opacity-60"
          >
            {running ? 'Running analysis…' : 'Run Analysis'}
          </button>
          {runError ? <p className="mt-3 text-sm text-rose-400">{runError}</p> : null}
        </section>
        <ProgressTracker events={events} running={running} />
      </div>
    </main>
  )
}
