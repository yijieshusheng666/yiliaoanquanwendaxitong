import { api } from './http'

export interface FeedbackStats {
  total: number
  likes: number
  dislikes: number
  satisfaction: number | null
}

export interface ReviewStats {
  pending: number
  resolved: number
  ignored: number
  total: number
}

export interface SystemStats {
  vector_docs: number
  interaction_pairs: number
  feedback: FeedbackStats
  review: ReviewStats
  mode: string
}

export function getStats() {
  return api.get<SystemStats>('/api/stats')
}