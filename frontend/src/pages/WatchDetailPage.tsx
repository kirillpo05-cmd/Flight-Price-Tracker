import { useEffect, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { formatDistanceToNow, format } from 'date-fns'
import { getWatch, patchWatch, deleteWatch, checkNow, getSnapshots } from '../api/watches'
import { listAlerts } from '../api/alerts'
import { PriceChart } from '../components/PriceChart'
import { AlertTable } from '../components/AlertTable'
import { RuleBadge } from '../components/RuleBadge'
import { useToast } from '../store/ToastContext'
import type { Watch, Snapshot, Alert } from '../types'

type Range = '7d' | '30d' | 'all'

const rangeFromDate: Record<Range, string | undefined> = {
  '7d': new Date(Date.now() - 7 * 86400 * 1000).toISOString().slice(0, 10),
  '30d': new Date(Date.now() - 30 * 86400 * 1000).toISOString().slice(0, 10),
  all: undefined,
}

function stopsLabel(stops: number): string {
  if (stops === 0) return 'Direct'
  return `${stops} stop${stops > 1 ? 's' : ''}`
}

function durationLabel(min?: number): string {
  if (!min) return ''
  const h = Math.floor(min / 60)
  const m = min % 60
  return m ? `${h}h ${m}m` : `${h}h`
}

export function WatchDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const toast = useToast()

  const [watch, setWatch] = useState<Watch | null>(null)
  const [snapshots, setSnapshots] = useState<Snapshot[]>([])
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [range, setRange] = useState<Range>('30d')
  const [loading, setLoading] = useState(true)
  const [checking, setChecking] = useState(false)

  const load = async () => {
    if (!id) return
    try {
      const [w, snaps, alts] = await Promise.all([
        getWatch(id),
        getSnapshots(id, rangeFromDate[range]),
        listAlerts(id, 50),
      ])
      setWatch(w)
      setSnapshots(snaps)
      setAlerts(alts)
    } catch (err: any) {
      if (err.response?.status === 404) {
        toast('Watch was deleted', 'info')
        navigate('/watches')
      } else {
        toast('Failed to load watch', 'error')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [id, range])

  const handlePause = async () => {
    if (!watch) return
    try {
      const updated = await patchWatch(watch.watch_id, { active: !watch.active })
      setWatch(updated)
      toast(updated.active ? 'Watch resumed' : 'Watch paused', 'success')
    } catch {
      toast('Failed to update watch', 'error')
    }
  }

  const handleDelete = async () => {
    if (!watch) return
    if (!confirm('Delete watch and all history?')) return
    try {
      await deleteWatch(watch.watch_id)
      toast('Watch deleted', 'success')
      navigate('/watches')
    } catch {
      toast('Failed to delete watch', 'error')
    }
  }

  const handleCheckNow = async () => {
    if (!watch) return
    setChecking(true)
    try {
      await checkNow(watch.watch_id)
      toast('Check triggered — refreshing in 10s', 'info')
      setTimeout(() => { load(); setChecking(false) }, 10000)
    } catch (err: any) {
      if (err.response?.status === 429) {
        toast('Check already running, please wait', 'info')
      } else {
        toast('Failed to trigger check', 'error')
      }
      setChecking(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    )
  }

  if (!watch) return null

  const offer = watch.last_offer
  const dateLabel =
    watch.date_mode === 'exact'
      ? [watch.depart_date, watch.return_date].filter(Boolean).join(' – ')
      : `${watch.date_from} – ${watch.date_to}`

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <Link to="/watches" className="text-sm text-gray-400 hover:text-gray-600 mb-1 block">
            ← All watches
          </Link>
          <h1 className="text-2xl font-bold text-gray-900">
            {watch.origin} → {watch.destination}
          </h1>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-gray-500 text-sm">{dateLabel}</span>
            <RuleBadge rule={watch.rule} />
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
              watch.active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
            }`}>
              {watch.active ? 'Active' : 'Paused'}
            </span>
          </div>
        </div>
        <div className="flex gap-2">
          <Btn onClick={handleCheckNow} disabled={checking}>
            {checking ? '⏳' : '🔄'} Check now
          </Btn>
          <Btn onClick={handlePause}>
            {watch.active ? '⏸ Pause' : '▶ Resume'}
          </Btn>
          <Btn onClick={handleDelete} danger>
            🗑 Delete
          </Btn>
        </div>
      </div>

      {/* Current offer + all-time low */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Current Best Offer
          </h3>
          {offer ? (
            <div>
              <div className="flex items-baseline gap-2 mb-2">
                <span className="text-4xl font-bold text-gray-900">
                  €{offer.price.toFixed(0)}
                </span>
                {offer.airline_name && (
                  <span className="text-gray-500 text-sm">{offer.airline_name}</span>
                )}
              </div>
              <div className="text-sm text-gray-500 space-y-1">
                <p>{stopsLabel(offer.stops)}{offer.duration_min ? ` · ${durationLabel(offer.duration_min)}` : ''}</p>
                {offer.depart_at && offer.arrive_at && (
                  <p>
                    {format(new Date(offer.depart_at), 'HH:mm')} →{' '}
                    {format(new Date(offer.arrive_at), 'HH:mm')}
                  </p>
                )}
              </div>
              {offer.deep_link && (
                <a
                  href={offer.deep_link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-3 inline-block bg-blue-600 text-white text-sm px-4 py-1.5 rounded-lg hover:bg-blue-700 transition-colors font-medium"
                >
                  Book
                </a>
              )}
            </div>
          ) : (
            <p className="text-sm text-gray-400">
              {watch.last_checked_at ? 'No offers found' : 'Not checked yet'}
            </p>
          )}
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
            All-Time Low
          </h3>
          {watch.lowest_seen != null ? (
            <div>
              <span className="text-4xl font-bold text-green-600">
                €{watch.lowest_seen.toFixed(0)}
              </span>
              {watch.lowest_seen_at && (
                <p className="text-sm text-gray-400 mt-1">
                  {format(new Date(watch.lowest_seen_at), 'MMM d, yyyy')}
                </p>
              )}
            </div>
          ) : (
            <p className="text-sm text-gray-400">No data yet</p>
          )}
          {watch.last_checked_at && (
            <p className="text-xs text-gray-300 mt-3">
              Last checked{' '}
              {formatDistanceToNow(new Date(watch.last_checked_at), { addSuffix: true })}
            </p>
          )}
        </div>
      </div>

      {/* Price chart */}
      <PriceChart
        snapshots={snapshots}
        watch={watch}
        range={range}
        onRangeChange={setRange}
      />

      {/* Alert log */}
      <AlertTable alerts={alerts} />
    </div>
  )
}

function Btn({
  children,
  onClick,
  disabled,
  danger,
}: {
  children: React.ReactNode
  onClick: () => void
  disabled?: boolean
  danger?: boolean
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 border ${
        danger
          ? 'border-red-200 text-red-600 hover:bg-red-50'
          : 'border-gray-200 text-gray-600 hover:bg-gray-50'
      }`}
    >
      {children}
    </button>
  )
}
