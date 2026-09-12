import { api } from './http'

export interface AuthResponse {
  user: { id: number; username: string; created_at: number; role?: string }
  token: string
}

export function register(username: string, password: string) {
  return api.post<AuthResponse>('/api/auth/register', { username, password })
}

export function login(username: string, password: string) {
  return api.post<AuthResponse>('/api/auth/login', { username, password })
}

export function logout() {
  return api.post<{ ok: boolean }>('/api/auth/logout')
}

export function me() {
  return api.get<{ user: { id: number; username: string; role?: string } }>('/api/auth/me')
}