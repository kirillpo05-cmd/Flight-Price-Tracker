import { Navigate, Outlet, Link, useLocation } from 'react-router-dom'
import { useAuth } from '../store/AuthContext'

export function ProtectedRoute() {
  const { token, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    )
  }
  if (!token) return <Navigate to="/login" state={{ from: location }} replace />
  return <Layout />
}

function Layout() {
  const { user, logout } = useAuth()
  const location = useLocation()

  const navLink = (to: string, label: string) => (
    <Link
      to={to}
      className={`text-sm font-medium transition-colors ${
        location.pathname.startsWith(to)
          ? 'text-blue-600'
          : 'text-gray-600 hover:text-gray-900'
      }`}
    >
      {label}
    </Link>
  )

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <Link to="/watches" className="font-bold text-blue-600 text-lg tracking-tight">
              ✈ FareWatch
            </Link>
            {navLink('/watches', 'Watches')}
            {navLink('/settings', 'Settings')}
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-500">{user?.email}</span>
            <PlanBadge plan={user?.plan ?? 'free'} />
            <button
              onClick={logout}
              className="text-sm text-gray-500 hover:text-gray-900 transition-colors"
            >
              Sign out
            </button>
          </div>
        </div>
      </nav>
      <main className="max-w-6xl mx-auto px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}

function PlanBadge({ plan }: { plan: string }) {
  const colors: Record<string, string> = {
    free: 'bg-gray-100 text-gray-600',
    pro: 'bg-blue-100 text-blue-700',
    team: 'bg-purple-100 text-purple-700',
  }
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full uppercase ${colors[plan] ?? colors.free}`}>
      {plan}
    </span>
  )
}
