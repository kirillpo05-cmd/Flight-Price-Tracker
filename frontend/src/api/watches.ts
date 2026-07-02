import client from './client'
import type { Watch, Snapshot, Rule } from '../types'

export const listWatches = async (): Promise<Watch[]> => {
  const { data } = await client.get<Watch[]>('/watches')
  return data
}

export const getWatch = async (id: string): Promise<Watch> => {
  const { data } = await client.get<Watch>(`/watches/${id}`)
  return data
}

export const createWatch = async (payload: {
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
}): Promise<Watch> => {
  const { data } = await client.post<Watch>('/watches', payload)
  return data
}

export const patchWatch = async (
  id: string,
  payload: { active?: boolean; rule?: Rule },
): Promise<Watch> => {
  const { data } = await client.patch<Watch>(`/watches/${id}`, payload)
  return data
}

export const deleteWatch = async (id: string): Promise<void> => {
  await client.delete(`/watches/${id}`)
}

export const checkNow = async (id: string): Promise<{ job_id: string }> => {
  const { data } = await client.post<{ job_id: string }>(`/watches/${id}/check`)
  return data
}

export const getSnapshots = async (
  id: string,
  fromDate?: string,
): Promise<Snapshot[]> => {
  const params: Record<string, string | number> = { limit: 200 }
  if (fromDate) params.from_date = fromDate
  const { data } = await client.get<Snapshot[]>(`/watches/${id}/snapshots`, { params })
  return data
}
