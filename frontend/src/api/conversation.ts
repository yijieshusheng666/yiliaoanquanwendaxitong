import { api } from './http'
import type { Conversation } from '@/types'

export function listConversations() {
  return api.get<{ conversations: Conversation[] }>('/api/conversations')
}

export function createConversation() {
  return api.post<{ session_id: string }>('/api/conversations')
}

export function deleteConversation(sessionId: string) {
  return api.del<{ ok: boolean }>(`/api/conversations/${sessionId}`)
}

export function getHistory(sessionId: string, limit = 0) {
  const q = limit > 0 ? `?session_id=${sessionId}&limit=${limit}` : `?session_id=${sessionId}`
  return api.get<{ session_id: string; history: { role: string; content: string }[] }>(
    `/api/history${q}`,
  )
}

export function sendFeedback(question: string, answer: string, rating: number, sessionId: string) {
  return api.post<{ ok: boolean }>('/api/feedback', {
    question,
    answer,
    rating,
    session_id: sessionId,
  })
}