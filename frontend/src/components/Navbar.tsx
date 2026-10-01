import { NavLink, useNavigate } from 'react-router-dom'

import { useAuth } from '../lib/auth'

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-lg px-3 py-2 text-sm font-medium transition ${
    isActive ? 'bg-cyan-500/15 text-cyan-300' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-100'
  }`

export default function Navbar() {
  const { email, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <header className="border-b border-slate-800 bg-night-900/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-cyan-500/20 text-cyan-300">
            <span className="text-sm font-bold">CD</span>
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-100">AI Cloud Cost Detective</p>
            <p className="text-xs text-slate-500">AWS + Gemini cost analysis</p>
          </div>
        </div>
        <nav className="flex items-center gap-1">
          <NavLink to="/" end className={linkClass}>
            Dashboard
          </NavLink>
          <NavLink to="/history" className={linkClass}>
            History
          </NavLink>
        </nav>
        <div className="flex items-center gap-3">
          <span className="hidden text-xs text-slate-400 sm:inline">{email}</span>
          <button
            type="button"
            onClick={() => {
              logout()
              navigate('/login')
            }}
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:border-slate-500 hover:text-white"
          >
            Log out
          </button>
        </div>
      </div>
    </header>
  )
}
