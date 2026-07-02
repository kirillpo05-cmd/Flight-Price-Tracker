import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { formatDistanceToNow } from 'date-fns'
import { patchWatch, deleteWatch, checkNow } from '../api/watches'
import { useToast } from '../store/ToastContext'
import { RuleBadge } from './RuleBadge'
import type { Watch } from '../types'

interface Props {
  watch: Watch
  onChange: () => void
}

export function WatchCard({ watch, onChange }: Props) {
  const navigate = useNavigate()
  const toast = useToast()
  const [checking, setChecking] = useState(false)

  const lastChecked = watch.last_checked_at
    ? formatDistanceToNow(new Date(watch.last_checked_at), { addSuffix: true })
    : 'Not checked yet'

  const isNearLow =
    watch.last_offer?.price != null &&
    watch.lowest_seen != null &&
    watch.last_offer.price <= watch.lowest_seen * 1.05

  const handlePause = async (e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await patchWatch(watch.watch_id, { active: !watch.active })
      toast(watch.active ? 'Watch paused' : 'Watch resumed', 'success')
      onChange()
    } catch {
      toast('Failed to update watch', 'error')
    }
  }

  const handleCheck = async (e: React.MouseEvent) => {
    e.stopPropagation()
    setChecking(true)
    try {
      await checkNow(watch.watch_id)
      toast('Check triggered', 'success')
      setTimeout(() => { onChange(); setChecking(false) }, 10000)
    } catch (err: any) {
      if (err.response?.status === 429) {
        toast('Check already running, please wait', 'info')
      } else {
        toast('Failed to trigger check', 'error')
      }
      setChecking(false)
    }
  }

  const handleDelete = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('Delete watch and all history?')) return
    try {
      await deleteWatch(watch.watch_id)
      toast('Watch deleted', 'success')
      onChange()
    } catch {
      toast('Failed to delete watch', 'error')
    }
  }

  const dateLabel =
    watch.date_mode === 'exact'
      ? [watch.depart_date, watch.return_date].filter(Boolean).join(' – ')
      : `${watch.date_from} – ${watch.date_to}`

  return (
    <div
      className="bg-white rounded-xl border border-gray-200 p-5 hover:shadow-md transition-shadow cursor-pointer"
      onClick={() => navigate(`/watches/${watch.watch_id}`)}
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-lg font-bold tracking-tight">
            {watch.origin} → {watch.destination}
          </h3>
          <p className="text-sm text-gray-500 mt-0.5">{dateLabel}</p>
        </div>
        <span
          className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
            watch.active
              ? 'bg-green-100 text-green-700'
              : 'bg-gray-100 text-gray-500'
          }`}
        >
          {watch.active ? 'Active' : 'Paused'}
        </span>
      </div>

      <div className="flex items-center gap-3 mb-3">
        {watch.last_offer?.price != null ? (
          <span
            className={`text-2xl font-bold ${
              isNearLow ? 'text-green-600' : 'text-gray-900'
            }`}
          >
            €{watch.last_offer.price.toFixed(0)}
          </span>
        ) : (
          <span className="text-sm text-gray-400">No price yet</span>
        )}
        <RuleBadge rule={watch.rule} />
      </div>

      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-400">{lastChecked}</p>
        <div className="flex gap-1">
          <IconBtn
            title={watch.active ? 'Pause' : 'Resume'}
            onClick={handlePause}
          >
            {watch.active ? '⏸' : '▶'}
          </IconBtn>
          <IconBtn title="Check now" onClick={handleCheck} disabled={checking}>
            {checking ? '⏳' : '🔄'}
          </IconBtn>
          <IconBtn title="Delete" onClick={handleDelete} danger>
            🗑
          </IconBtn>
        </div>
      </div>
    </div>
  )
}

function IconBtn({
  children,
  onClick,
  title,
  disabled,
  danger,
}: {
  children: React.ReactNode
  onClick: (e: React.MouseEvent) => void
  title?: string
  disabled?: boolean
  danger?: boolean
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={`p-1.5 rounded-lg text-sm transition-colors disabled:opacity-50 ${
        danger
          ? 'hover:bg-red-50 text-gray-500 hover:text-red-600'
          : 'hover:bg-gray-100 text-gray-500'
      }`}
    >
      {children}
    </button>
  )
}
