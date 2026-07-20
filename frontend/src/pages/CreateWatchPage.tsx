import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { createWatch } from '../api/watches'
import { useToast } from '../store/ToastContext'
import { AirportAutocomplete } from '../components/AirportAutocomplete'
import type { Rule } from '../types'

type RuleType = Rule['type']

export function CreateWatchPage() {
  const navigate = useNavigate()
  const toast = useToast()

  const [origin, setOrigin] = useState('')
  const [destination, setDestination] = useState('')
  const [dateMode, setDateMode] = useState<'exact' | 'range'>('exact')
  const [departDate, setDepartDate] = useState('')
  const [returnDate, setReturnDate] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [passengers, setPassengers] = useState(1)
  const [cabin, setCabin] = useState('economy')
  const [ruleType, setRuleType] = useState<RuleType>('threshold')
  const [thresholdPrice, setThresholdPrice] = useState('')
  const [dropPct, setDropPct] = useState('')
  const [digestTime, setDigestTime] = useState('08:00')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const swap = () => {
    setOrigin(destination)
    setDestination(origin)
  }

  const buildRule = (): Rule => {
    switch (ruleType) {
      case 'threshold': return { type: 'threshold', threshold_price: parseFloat(thresholdPrice) }
      case 'drop_pct': return { type: 'drop_pct', drop_pct: parseFloat(dropPct) }
      case 'digest': return { type: 'digest', digest_time: digestTime }
      default: return { type: 'new_low' }
    }
  }

  const isValid =
    origin.trim().length === 3 &&
    destination.trim().length === 3 &&
    (dateMode === 'exact' ? !!departDate : !!dateFrom && !!dateTo) &&
    (ruleType !== 'threshold' || !!thresholdPrice) &&
    (ruleType !== 'drop_pct' || !!dropPct)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!isValid) return
    setSubmitting(true)
    setError('')
    try {
      const w = await createWatch({
        origin: origin.toUpperCase(),
        destination: destination.toUpperCase(),
        date_mode: dateMode,
        depart_date: dateMode === 'exact' ? departDate : undefined,
        return_date: dateMode === 'exact' && returnDate ? returnDate : undefined,
        date_from: dateMode === 'range' ? dateFrom : undefined,
        date_to: dateMode === 'range' ? dateTo : undefined,
        passengers,
        cabin,
        rule: buildRule(),
      })
      toast('Watch created!', 'success')
      navigate(`/watches/${w.watch_id}`)
    } catch (err: any) {
      const d = err.response?.data
      if (d?.error === 'plan_limit_reached') {
        setError(`Plan limit reached (${d.current}/${d.limit}). Upgrade to add more watches.`)
      } else {
        setError(d?.detail ?? 'Failed to create watch')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="max-w-xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">New Watch</h1>

      {error && (
        <div className="mb-4 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Route */}
        <Section title="Route">
          <div className="flex items-center gap-2">
            <div className="flex-1">
              <label className="block text-xs text-gray-500 mb-1">Origin</label>
              <AirportAutocomplete value={origin} onChange={setOrigin} placeholder="Riga, RIX…" />
            </div>
            <button
              type="button"
              onClick={swap}
              className="mt-5 p-2 text-gray-400 hover:text-gray-600 transition-colors text-lg"
              title="Swap"
            >
              ⇄
            </button>
            <div className="flex-1">
              <label className="block text-xs text-gray-500 mb-1">Destination</label>
              <AirportAutocomplete value={destination} onChange={setDestination} placeholder="Barcelona, BCN…" />
            </div>
          </div>
        </Section>

        {/* Dates */}
        <Section title="Dates">
          <div className="flex gap-2 mb-3">
            {(['exact', 'range'] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setDateMode(m)}
                className={`flex-1 py-1.5 text-sm rounded-lg font-medium transition-colors border ${
                  dateMode === m
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'bg-white text-gray-600 border-gray-300 hover:border-gray-400'
                }`}
              >
                {m === 'exact' ? 'Exact dates' : 'Date range'}
              </button>
            ))}
          </div>

          {dateMode === 'exact' ? (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">Departure</label>
                <input
                  type="date"
                  value={departDate}
                  onChange={(e) => setDepartDate(e.target.value)}
                  required
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Return (optional)</label>
                <input
                  type="date"
                  value={returnDate}
                  onChange={(e) => setReturnDate(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">From</label>
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  required
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">To</label>
                <input
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  required
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
          )}
        </Section>

        {/* Passengers & Cabin */}
        <Section title="Passengers &amp; Cabin">
          <div className="flex gap-4 items-center">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Passengers</label>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setPassengers(Math.max(1, passengers - 1))}
                  className="w-8 h-8 rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 font-bold"
                >
                  –
                </button>
                <span className="w-6 text-center font-semibold">{passengers}</span>
                <button
                  type="button"
                  onClick={() => setPassengers(Math.min(9, passengers + 1))}
                  className="w-8 h-8 rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50 font-bold"
                >
                  +
                </button>
              </div>
            </div>
            <div className="flex-1">
              <label className="block text-xs text-gray-500 mb-1">Cabin</label>
              <select
                value={cabin}
                onChange={(e) => setCabin(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="economy">Economy</option>
                <option value="business">Business</option>
                <option value="first">First</option>
              </select>
            </div>
          </div>
        </Section>

        {/* Alert Rule */}
        <Section title="Alert Rule">
          <div className="grid grid-cols-2 gap-2 mb-3">
            {([
              ['threshold', '< Price'],
              ['new_low', 'New Low'],
              ['drop_pct', 'Drop %'],
              ['digest', 'Digest'],
            ] as [RuleType, string][]).map(([t, label]) => (
              <button
                key={t}
                type="button"
                onClick={() => setRuleType(t)}
                className={`py-2 text-sm rounded-lg font-medium transition-colors border ${
                  ruleType === t
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'bg-white text-gray-600 border-gray-300 hover:border-gray-400'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {ruleType === 'threshold' && (
            <div>
              <label className="block text-xs text-gray-500 mb-1">Alert when price below (€)</label>
              <input
                type="number"
                min="1"
                step="1"
                value={thresholdPrice}
                onChange={(e) => setThresholdPrice(e.target.value)}
                required
                placeholder="e.g. 90"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          )}
          {ruleType === 'drop_pct' && (
            <div>
              <label className="block text-xs text-gray-500 mb-1">Alert when price drops by (%)</label>
              <input
                type="number"
                min="1"
                max="99"
                step="1"
                value={dropPct}
                onChange={(e) => setDropPct(e.target.value)}
                required
                placeholder="e.g. 15"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          )}
          {ruleType === 'digest' && (
            <div>
              <label className="block text-xs text-gray-500 mb-1">Daily digest time (UTC)</label>
              <input
                type="time"
                value={digestTime}
                onChange={(e) => setDigestTime(e.target.value)}
                required
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          )}
          {ruleType === 'new_low' && (
            <p className="text-sm text-gray-400">Alert when a new all-time low price is found.</p>
          )}
        </Section>

        <button
          type="submit"
          disabled={!isValid || submitting}
          className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-semibold py-2.5 rounded-lg transition-colors"
        >
          {submitting ? 'Creating…' : 'Create Watch'}
        </button>
      </form>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-4">
        {title}
      </h2>
      {children}
    </div>
  )
}
