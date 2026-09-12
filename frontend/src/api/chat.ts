// SSE 流式问答：POST /api/chat 返回 text/event-stream，逐事件回调。
import { getToken } from './http'
import type { EventPayload } from '@/types'

export interface ChatRequest {
  question: string
  session_id?: string
  history?: { role: string; content: string }[]
}

type EventHandler = (ev: EventPayload) => void

export async function streamChat(
  req: ChatRequest,
  onEvent: EventHandler,
): Promise<void> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  const resp = await fetch('/api/chat', {
    method: 'POST',
    headers,
    body: JSON.stringify({ ...req, stream: true }),
  })

  if (!resp.ok || !resp.body) {
    let detail = `请求失败 (${resp.status})`
    try {
      const body = await resp.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  // SSE 帧间以空行分隔，每帧形如 "data: {...}\n\n"；按 \n\n 切分以兼容跨块事件
  const dispatch = (chunk: string): boolean => {
    for (const line of chunk.split('\n')) {
      const s = line.trim()
      if (!s.startsWith('data:')) continue
      const payload = s.slice(5).trim()
      if (!payload) continue
      try {
        onEvent(JSON.parse(payload) as EventPayload)
      } catch {
        /* 忽略无法解析的帧 */
      }
    }
    return true
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let idx = buffer.indexOf('\n\n')
    while (idx !== -1) {
      const frame = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      dispatch(frame)
      idx = buffer.indexOf('\n\n')
    }
  }
  if (buffer.trim()) dispatch(buffer)
}