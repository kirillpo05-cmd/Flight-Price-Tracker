import client from './client'
import type { User } from '../types'

export const register = (email: string, password: string) =>
  client.post('/auth/register', { email, password })

export const login = async (email: string, password: string): Promise<string> => {
  const { data } = await client.post<{ access_token: string }>('/auth/login', {
    email,
    password,
  })
  return data.access_token
}

export const getMe = async (): Promise<User> => {
  const { data } = await client.get<User>('/auth/me')
  return data
}

export const patchMe = async (payload: {
  telegram_chat_id?: number | null
}): Promise<User> => {
  const { data } = await client.patch<User>('/auth/me', payload)
  return data
}

export const changePassword = async (
  old_password: string,
  new_password: string,
): Promise<void> => {
  await client.post('/auth/change-password', { old_password, new_password })
}

export const deleteMe = async (): Promise<void> => {
  await client.delete('/auth/me')
}
