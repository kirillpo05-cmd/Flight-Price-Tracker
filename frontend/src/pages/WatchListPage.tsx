import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listWatches } from '../api/watches'
import { WatchCard } from '../components/WatchCard'
import { useAuth } from '../store/AuthContext'
import { PLAN_LIMITS } from '../types'
import type { Watch } from '../types'

export function WatchListPage() {
  const { user } = useAuth()
  const [watches, setWatches] = useState<Watch[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetch = async () => {
    try {
      const data = await listWatches()
      setWatches(data)
    } catch {
      setError('Failed to load watches')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetch() }, [])

  const plan = user?.plan ?? 'free'
  const limit = PLAN_LIMITS[plan] ?? 3
  const atLimit = watches.length >= limit

  if (loading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="bg-white rounded-xl border border-gray-200 p-5 h-40 animate-pulse">
            <div className="h-4 bg-gray-100 rounded w-2/3 mb-3" />
            <div className="h-6 bg-gray-100 rounded w-1/3 mb-4" />
            <div className="h-3 bg-gray-100 rounded w-1/2" />
          </div>
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-16">
        <p className="text-red-500 mb-4">{error}</p>
        <button onClick={fetch} className="text-blue-600 hover:underline text-sm">
          Retry
        </button>
      </div>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">My Watches</h1>
        <Link
          to={atLimit ? '#' : '/watches/new'}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-colors ${
            atLimit
              ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
              : 'bg-blue-600 text-white hover:bg-blue-700'
          }`}
          onClick={(e) => atLimit && e.preventDefault()}
        >
          + New Watch
        </Link>
      </div>

      {atLimit && (
        <div className="mb-5 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm text-amber-800 flex items-center justify-between">
          <span>
            Plan limit reached ({watches.length}/{limit}). Upgrade to{' '}
            <strong>Pro</strong> for 30 watches.
          </span>
        </div>
      )}

      {watches.length === 0 ? (
        <div className="text-center py-24">
          <div className="text-5xl mb-4">✈</div>
          <h2 className="text-xl font-semibold text-gray-700 mb-2">No watches yet</h2>
          <p className="text-gray-400 mb-6 text-sm">
            Create your first watch to start tracking flight prices.
          </p>
          <Link
            to="/watches/new"
            className="bg-blue-600 text-white px-6 py-2 rounded-lg font-semibold text-sm hover:bg-blue-700 transition-colors"
          >
            Create first watch
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {watches.map((w) => (
            <WatchCard key={w.watch_id} watch={w} onChange={fetch} />
          ))}
        </div>
      )}
    </div>
  )
}
