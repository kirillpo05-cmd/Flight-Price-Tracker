import { format } from 'date-fns'
import type { Alert } from '../types'

const STATUS_ICONS: Record<string, string> = {
  sent: '✓',
  partial: '⚠',
  failed: '✗',
}
const STATUS_COLORS: Record<string, string> = {
  sent: 'text-green-600',
  partial: 'text-amber-600',
  failed: 'text-red-500',
}

export function AlertTable({ alerts }: { alerts: Alert[] }) {
  if (alerts.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h3 className="font-semibold text-gray-900 mb-3">Alert Log</h3>
        <p className="text-sm text-gray-400">No alerts yet.</p>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <h3 className="font-semibold text-gray-900 mb-3">Alert Log</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-400 border-b border-gray-100">
              <th className="pb-2 font-medium">Time</th>
              <th className="pb-2 font-medium">Type</th>
              <th className="pb-2 font-medium">Price</th>
              <th className="pb-2 font-medium">Channel</th>
              <th className="pb-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {alerts.map((a) => (
              <tr key={a.alert_id} className="hover:bg-gray-50 transition-colors">
                <td className="py-2 text-gray-600">
                  {format(new Date(a.triggered_at), 'MMM d, HH:mm')}
                </td>
                <td className="py-2">
                  <span className="capitalize text-gray-700">
                    {a.rule_type.replace('_', ' ')}
                  </span>
                </td>
                <td className="py-2 font-medium text-gray-900">
                  {a.price != null ? `€${a.price.toFixed(0)}` : '—'}
                </td>
                <td className="py-2 text-gray-600 capitalize">{a.channel}</td>
                <td className="py-2">
                  <span
                    className={`font-semibold ${STATUS_COLORS[a.status] ?? 'text-gray-500'}`}
                    title={a.error ?? undefined}
                  >
                    {STATUS_ICONS[a.status] ?? a.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
