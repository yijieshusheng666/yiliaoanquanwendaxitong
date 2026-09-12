import { api } from './http'

export interface DocItem {
  name: string
  size: number
  chunks: number
  updated_at: number
}

export interface DocSection {
  section: string
  text: string
}

export interface IndexVersion {
  name: string
  path: string
  corpus_fingerprint: string
  stats: Record<string, number>
  built_at: string
  status: string
}

export function listDocuments() {
  return api.get<{ documents: DocItem[]; total: number }>('/api/admin/documents')
}

export function upsertDocument(name: string, content: string) {
  return api.post<{ ok: boolean; name: string; existed: boolean; hint?: string }>(
    '/api/admin/documents',
    { name, content },
  )
}

export function deleteDocument(name: string) {
  return api.del<{ ok: boolean }>(`/api/admin/documents/${encodeURIComponent(name)}`)
}

export function previewDocument(name: string) {
  return api.get<{ name: string; chunk_count: number; sections: DocSection[] }>(
    `/api/admin/documents/${encodeURIComponent(name)}`,
  )
}

export function getIndexState() {
  return api.get<{
    ready: boolean
    current: IndexVersion | null
    versions: IndexVersion[]
    dir: string
  }>('/api/admin/index')
}

export function rebuildIndex() {
  return api.post<{ ok: boolean; chunk_count: number }>('/api/admin/index/rebuild')
}

export function rollbackIndex() {
  return api.post<{ ok: boolean; current: string }>('/api/admin/index/rollback')
}

export interface ReviewItem {
  id: number
  question: string
  answer: string
  session_id: string
  user_id: string
  count: number
  status: string
  note: string
  reviewed_by: string
  created_at: number
  reviewed_at: number | null
}

export function listReviews(status = '') {
  return api.get<{ reviews: ReviewItem[]; summary: Record<string, number> }>(
    `/api/admin/reviews${status ? `?status=${status}` : ''}`,
  )
}

export function resolveReview(
  id: number,
  body: { status: string; note: string; drug: string; content: string },
) {
  return api.post<{ ok: boolean; reflowed: boolean; hint?: string }>(
    `/api/admin/reviews/${id}/resolve`,
    body,
  )
}