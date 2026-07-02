import type { Rule } from '../types'

export function RuleBadge({ rule }: { rule: Rule }) {
  const labels: Record<string, string> = {
    threshold: `< €${rule.threshold_price?.toFixed(0)}`,
    new_low: 'New low',
    drop_pct: `–${rule.drop_pct?.toFixed(0)}%`,
    digest: `Digest ${rule.digest_time}`,
  }
  const colors: Record<string, string> = {
    threshold: 'bg-amber-100 text-amber-800',
    new_low: 'bg-green-100 text-green-800',
    drop_pct: 'bg-blue-100 text-blue-800',
    digest: 'bg-gray-100 text-gray-700',
  }
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
        colors[rule.type] ?? 'bg-gray-100 text-gray-700'
      }`}
    >
      {labels[rule.type] ?? rule.type}
    </span>
  )
}
