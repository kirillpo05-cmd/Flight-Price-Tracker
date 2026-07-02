export interface User {
  user_id: string
  email: string
  plan: 'free' | 'pro' | 'team'
  telegram_chat_id: number | null
  created_at: string
}

export interface Rule {
  type: 'threshold' | 'new_low' | 'drop_pct' | 'digest'
  threshold_price?: number
  drop_pct?: number
  digest_time?: string
}

export interface Offer {
  price: number
  airline: string
  airline_name?: string
  stops: number
  depart_at?: string
  arrive_at?: string
  duration_min?: number
  deep_link?: string
}

export interface Watch {
  watch_id: string
  user_id: string
  origin: string
  destination: string
  date_mode: 'exact' | 'range'
  depart_date?: string
  return_date?: string
  date_from?: string
  date_to?: string
  passengers: number
  cabin: string
  rule: Rule
  active: boolean
  lowest_seen?: number
  lowest_seen_at?: string
  last_checked_at?: string
  last_alerted_at?: string
  last_offer?: Offer
  created_at: string
  updated_at: string
}

export interface Snapshot {
  checked_at: string
  price: number | null
  airline?: string
  airline_name?: string
  stops?: number
}

export interface Alert {
  alert_id: string
  watch_id: string
  rule_type: string
  triggered_at: string
  price?: number
  offer?: Offer
  channel: string
  status: 'sent' | 'failed' | 'partial'
  error?: string
}

export const PLAN_LIMITS: Record<string, number> = {
  free: 3,
  pro: 30,
  team: 150,
}
