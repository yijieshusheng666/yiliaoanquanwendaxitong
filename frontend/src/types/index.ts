// 与后端 SSE 事件协议、REST 返回结构对应的类型定义

export interface Source {
  drug: string
  section: string
  text: string
}

export interface Citation {
  ok: boolean
  cited: number[]
  out_of_range: number[]
  missing_anchor: number[]
  sources_empty: boolean
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
  citation?: Citation
  emergency?: boolean
  noMatch?: boolean
  pending?: boolean
  error?: boolean
}

export interface Conversation {
  id: string
  title: string
  created_at: number
  updated_at: number
  msg_count: number
}

export interface User {
  id: number
  username: string
  created_at: number
  role?: string
}

export interface EventPayload {
  type: string
  content?: string
  sources?: Source[]
  citation?: Citation
  keyword?: string
  path?: string
  mode?: string
  answer?: string
  message?: string
  interaction?: boolean
  no_match?: boolean
  [key: string]: unknown
}