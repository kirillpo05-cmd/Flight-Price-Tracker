import client from './client'
import type { Alert } from '../types'

export const listAlerts = async (watchId?: string, limit = 20): Promise<Alert[]> => {
  const params: Record<string, string | number> = { limit }
  if (watchId) params.watch_id = watchId
  const { data } = await client.get<Alert[]>('/alerts', { params })
  return data
}
