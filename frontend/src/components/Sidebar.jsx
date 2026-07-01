import { NavLink } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

const BASE = 'flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors'

/** Navigable item when `to` is set; otherwise a decorative (disabled) item. */
const NavItem = ({ icon, label, to, end = false }) => {
  if (!to) {
    return (
      <div className={`${BASE} text-slate-300 cursor-default`}>
        {icon}
        {label}
      </div>
    )
  }
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `${BASE} ${isActive
          ? 'bg-blue-700 text-white'
          : 'text-slate-300 hover:bg-slate-700 hover:text-white'}`
      }
    >
      {icon}
      {label}
    </NavLink>
  )
}

export default function Sidebar() {
  const { user, role, logout } = useAuth()

  return (
    <aside className="w-60 bg-slate-900 flex flex-col shrink-0">
      {/* Brand */}
      <div className="h-14 flex items-center px-5 border-b border-slate-700">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center">
            <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <span className="text-white font-semibold text-sm">MM Validator Tool</span>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-3 space-y-1">
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider px-3 mb-2 mt-1">
          Main
        </p>
        <NavItem
          to="/"
          end
          label="Validator"
          icon={
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
            </svg>
          }
        />

        {role === 'admin' && (
          <>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider px-3 mb-2 mt-4">
              Admin Activities
            </p>
            <NavItem
              to="/ai-configuration"
              label="AI Configuration"
              icon={
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
              }
            />
          </>
        )}

        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider px-3 mb-2 mt-4">
          Info
        </p>
        <NavItem
          to="/about"
          label="About"
          icon={
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          }
        />
      </nav>

      {/* User / logout */}
      <div className="p-3 border-t border-slate-700">
        <div className="flex items-center gap-3 px-3 py-2">
          <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center text-white text-xs font-bold uppercase">
            {user?.[0] ?? 'U'}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-slate-200 truncate">{user}</p>
            <p className="text-xs text-slate-500 capitalize">{role || 'Authenticated'}</p>
          </div>
          <button
            onClick={logout}
            title="Sign out"
            className="text-slate-400 hover:text-white transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
          </button>
        </div>
      </div>
    </aside>
  )
}
