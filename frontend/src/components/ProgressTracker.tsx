import type { ProgressEvent } from '../types'

type Props = {
  events: ProgressEvent[]
  running: boolean
}

export default function ProgressTracker({ events, running }: Props) {
  const latest = events[events.length - 1]
  const percent = latest?.percent ?? 0
  const status = latest?.status ?? (running ? 'running' : 'idle')

  return (
    <section className="rounded-2xl border border-slate-800 bg-night-900 p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Live progress</h2>
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-medium ${
            status === 'complete'
              ? 'bg-emerald-500/15 text-emerald-300'
              : status === 'failed'
                ? 'bg-rose-500/15 text-rose-300'
                : running
                  ? 'bg-cyan-500/15 text-cyan-300'
                  : 'bg-slate-800 text-slate-400'
          }`}
        >
          {status}
        </span>
      </div>
      <div className="mb-3 h-2 overflow-hidden rounded-full bg-slate-800">
        <div
          className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-teal-400 transition-all duration-500"
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="mb-4 text-sm text-slate-200">{latest?.message ?? 'Waiting to start an analysis…'}</p>
      <ol className="space-y-2">
        {events.length === 0 ? (
          <li className="text-sm text-slate-500">WebSocket updates will appear here.</li>
        ) : (
          events.map((event, index) => (
            <li key={`${event.message}-${index}`} className="flex gap-3 text-sm">
              <span className="w-10 shrink-0 font-mono text-xs text-cyan-400">{event.percent}%</span>
              <span className="text-slate-300">{event.message}</span>
            </li>
          ))
        )}
      </ol>
    </section>
  )
}
