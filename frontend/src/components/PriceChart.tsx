import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  TooltipProps,
} from 'recharts'
import { format } from 'date-fns'
import type { Snapshot, Watch } from '../types'

type Range = '7d' | '30d' | 'all'

interface Props {
  snapshots: Snapshot[]
  watch: Watch
  range: Range
  onRangeChange: (r: Range) => void
}

interface ChartPoint {
  ts: number
  price: number | null
  label: string
  airline?: string
}

function filterByRange(snapshots: Snapshot[], range: Range): Snapshot[] {
  if (range === 'all') return snapshots
  const days = range === '7d' ? 7 : 30
  const cutoff = Date.now() - days * 86400 * 1000
  return snapshots.filter((s) => new Date(s.checked_at).getTime() >= cutoff)
}

function CustomTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload as ChartPoint
  return (
    <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 shadow text-sm">
      <p className="text-gray-500 text-xs mb-1">{d.label}</p>
      {d.price != null ? (
        <>
          <p className="font-bold text-gray-900">€{d.price.toFixed(0)}</p>
          {d.airline && <p className="text-gray-500 text-xs">{d.airline}</p>}
        </>
      ) : (
        <p className="text-gray-400">No offers</p>
      )}
    </div>
  )
}

export function PriceChart({ snapshots, watch, range, onRangeChange }: Props) {
  const filtered = filterByRange(snapshots, range)

  const data: ChartPoint[] = filtered
    .sort((a, b) => new Date(a.checked_at).getTime() - new Date(b.checked_at).getTime())
    .map((s) => ({
      ts: new Date(s.checked_at).getTime(),
      price: s.price,
      label: format(new Date(s.checked_at), 'MMM d, HH:mm'),
      airline: s.airline_name ?? s.airline,
    }))

  const hasData = data.length > 0
  const hasOffers = data.some((d) => d.price != null)

  const yMin = hasOffers
    ? Math.floor(Math.min(...data.filter((d) => d.price != null).map((d) => d.price!)) * 0.95)
    : undefined
  const yMax = hasOffers
    ? Math.ceil(Math.max(...data.filter((d) => d.price != null).map((d) => d.price!)) * 1.05)
    : undefined

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-gray-900">Price History</h3>
        <div className="flex gap-1">
          {(['7d', '30d', 'all'] as Range[]).map((r) => (
            <button
              key={r}
              onClick={() => onRangeChange(r)}
              className={`px-3 py-1 text-xs rounded-lg font-medium transition-colors ${
                range === r
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-500 hover:bg-gray-100'
              }`}
            >
              {r === 'all' ? 'All' : r}
            </button>
          ))}
        </div>
      </div>

      {!hasData ? (
        <div className="h-48 flex items-center justify-center text-sm text-gray-400">
          No data yet. First check hasn't completed.
        </div>
      ) : !hasOffers ? (
        <div className="h-48 flex items-center justify-center text-sm text-gray-400">
          No offers found. Try changing the dates.
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 11, fill: '#9ca3af' }}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              domain={[yMin!, yMax!]}
              tick={{ fontSize: 11, fill: '#9ca3af' }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => `€${v}`}
              width={50}
            />
            <Tooltip content={<CustomTooltip />} />
            {watch.rule.type === 'threshold' && watch.rule.threshold_price != null && (
              <ReferenceLine
                y={watch.rule.threshold_price}
                stroke="#f59e0b"
                strokeDasharray="4 4"
                label={{ value: `Threshold €${watch.rule.threshold_price}`, fontSize: 11, fill: '#f59e0b', position: 'right' }}
              />
            )}
            {watch.lowest_seen != null && (
              <ReferenceLine
                y={watch.lowest_seen}
                stroke="#10b981"
                strokeDasharray="4 4"
                label={{ value: `Low €${watch.lowest_seen.toFixed(0)}`, fontSize: 11, fill: '#10b981', position: 'right' }}
              />
            )}
            <Line
              type="monotone"
              dataKey="price"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={data.length === 1 ? { r: 4 } : false}
              connectNulls={false}
              activeDot={{ r: 5 }}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
