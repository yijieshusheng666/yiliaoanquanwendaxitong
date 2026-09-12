<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, Delete, SwitchButton, Promotion } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { streamChat } from '@/api/chat'
import {
  listConversations,
  createConversation,
  deleteConversation,
  getHistory,
  sendFeedback,
} from '@/api/conversation'
import type { ChatMessage, Conversation, EventPayload } from '@/types'

const router = useRouter()
const auth = useAuthStore()

const conversations = ref<Conversation[]>([])
const activeId = ref('')
const messages = ref<ChatMessage[]>([])
const input = ref('')
const sending = ref(false)
const scrollRef = ref<HTMLElement>()

function msgId() {
  return `m_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

onMounted(async () => {
  auth.restore()
  await refreshConversations()
})

async function refreshConversations() {
  try {
    const res = await listConversations()
    conversations.value = res.conversations
  } catch {
    conversations.value = []
  }
}

async function newSession() {
  // 已存在空白对话时不重复新建，直接切换到它，保证空白对话最多一个
  const blank = conversations.value.find((c) => c.msg_count === 0)
  if (blank) {
    activeId.value = blank.id
    messages.value = []
    return
  }
  try {
    const res = await createConversation()
    activeId.value = res.session_id
    messages.value = []
    await refreshConversations()
  } catch {
    ElMessage.warning('以游客身份时需先登录才能保存会话')
  }
}

async function switchSession(c: Conversation) {
  activeId.value = c.id
  messages.value = []
  try {
    const res = await getHistory(c.id)
    messages.value = res.history.map((h) => ({
      id: msgId(),
      role: h.role as 'user' | 'assistant',
      content: h.content,
    }))
  } catch {
    /* 历史加载失败不阻塞 */
  }
  scrollToBottom()
}

async function removeSession(c: Conversation) {
  try {
    await deleteConversation(c.id)
    if (activeId.value === c.id) {
      activeId.value = ''
      messages.value = []
    }
    await refreshConversations()
  } catch {
    ElMessage.error('删除失败')
  }
}

function scrollToBottom() {
  nextTick(() => {
    scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight, behavior: 'smooth' })
  })
}

async function send() {
  const question = input.value.trim()
  if (!question || sending.value) return
  input.value = ''
  sending.value = true

  // 无会话时先建会话（游客也能建，只是不落盘归属）
  if (!activeId.value) {
    try {
      const res = await createConversation()
      activeId.value = res.session_id
      await refreshConversations()
    } catch {
      /* 建会话失败仍可继续问答 */
    }
  }

  const userMsg: ChatMessage = { id: msgId(), role: 'user', content: question }
  const assistantMsg: ChatMessage = {
    id: msgId(),
    role: 'assistant',
    content: '',
    pending: true,
  }
  messages.value.push(userMsg, assistantMsg)
  scrollToBottom()

  const history = messages.value
    .filter((m) => m.id !== assistantMsg.id && !m.pending)
    .slice(-6)
    .map((m) => ({ role: m.role, content: m.content }))

  try {
    await streamChat(
      { question, session_id: activeId.value || undefined, history },
      (ev: EventPayload) => handleEvent(ev, assistantMsg),
    )
  } catch (e) {
    assistantMsg.content = e instanceof Error ? e.message : '请求出错，请稍后重试'
    assistantMsg.error = true
    assistantMsg.pending = false
  } finally {
    sending.value = false
    assistantMsg.pending = false
    scrollToBottom()
    await refreshConversations()
  }
}

function handleEvent(ev: EventPayload, msg: ChatMessage) {
  switch (ev.type) {
    case 'token':
      msg.content += ev.content || ''
      scrollToBottom()
      break
    case 'emergency':
      msg.content = ev.content || ''
      msg.emergency = true
      msg.pending = false
      break
    case 'sources':
      msg.sources = ev.sources
      msg.citation = ev.citation
      break
    case 'done':
      if (!msg.content && ev.answer) msg.content = ev.answer
      msg.sources = ev.sources || msg.sources
      msg.citation = ev.citation || msg.citation
      msg.noMatch = !!ev.no_match
      msg.pending = false
      break
    case 'error':
      msg.content = ev.message || '生成回答时发生错误'
      msg.error = true
      msg.pending = false
      break
  }
}

async function rate(msg: ChatMessage, rating: number) {
  const prevUser = messages.value
    .filter((m) => m.role === 'user')
    .slice(-1)[0]
  try {
    await sendFeedback(prevUser?.content || '', msg.content, rating, activeId.value || '')
    ElMessage.success(rating === 1 ? '感谢反馈' : '已记录，我们会改进')
  } catch {
    ElMessage.warning('反馈提交失败')
  }
}

function logout() {
  auth.logout()
  router.push('/')
}
</script>

<template>
  <div class="chat-layout">
    <!-- 侧边栏：会话列表 -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <span class="brand">💊 医疗安全问答</span>
        <el-button type="primary" :icon="Plus" circle size="small" @click="newSession" />
      </div>

      <div class="session-list">
        <div
          v-for="c in conversations"
          :key="c.id"
          class="session-item"
          :class="{ active: c.id === activeId }"
          @click="switchSession(c)"
        >
          <span class="session-title">{{ c.title }}</span>
          <el-button
            :icon="Delete"
            text
            size="small"
            class="del-btn"
            @click.stop="removeSession(c)"
          />
        </div>
        <div v-if="!conversations.length" class="empty">暂无历史会话</div>
      </div>

      <div class="sidebar-footer">
        <div class="user-line">
          <span>{{ auth.username }}</span>
          <el-tag v-if="auth.isAdmin" size="small" type="warning">管理员</el-tag>
        </div>
        <div class="footer-actions">
          <el-button text size="small" @click="router.push('/')">首页</el-button>
          <el-button
            text
            size="small"
            :icon="SwitchButton"
            @click="auth.isLoggedIn ? logout() : router.push('/login')"
          >
            {{ auth.isLoggedIn ? '退出' : '登录' }}
          </el-button>
        </div>
      </div>
    </aside>

    <!-- 主聊天区 -->
    <main class="chat-main">
      <div class="chat-scroll" ref="scrollRef">
        <div class="message-list">
          <div v-if="!messages.length" class="welcome">
            <div class="welcome-icon">💬</div>
            <p>您好，请问有什么用药方面的问题需要咨询？</p>
          </div>

          <div
            v-for="m in messages"
            :key="m.id"
            class="msg-row"
            :class="m.role"
          >
            <div class="bubble" :class="{ emergency: m.emergency, error: m.error }">
              <div v-if="m.pending && !m.content" class="typing">
                <span></span><span></span><span></span>
              </div>
              <div v-else class="markdown-body">{{ m.content }}</div>

              <div v-if="m.citation && !m.citation.ok" class="citation-warning">
                ⚠️ 部分引用未通过来源校验，请谨慎采信
              </div>

              <details v-if="m.sources && m.sources.length" class="sources">
                <summary>引用来源（{{ m.sources.length }}）</summary>
                <ul>
                  <li v-for="(s, i) in m.sources" :key="i">
                    <strong>{{ s.drug }}</strong> · {{ s.section }}
                    <span class="src-text">{{ s.text }}</span>
                  </li>
                </ul>
              </details>

              <div v-if="m.role === 'assistant' && !m.pending && m.content" class="rate-row">
                <el-button text size="small" @click="rate(m, 1)">👍</el-button>
                <el-button text size="small" @click="rate(m, -1)">👎</el-button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="input-bar">
        <el-input
          v-model="input"
          type="textarea"
          :rows="2"
          resize="none"
          placeholder="请输入您的问题，例如：布洛芬和阿司匹林能一起吃吗？"
          :disabled="sending"
          @keydown.enter.exact.prevent="send"
        />
        <el-button
          type="primary"
          :icon="Promotion"
          :loading="sending"
          class="send-btn"
          @click="send"
        >
          发送
        </el-button>
      </div>
      <div class="disclaimer">内容仅供学习参考，不构成医疗建议。如有不适请及时就医。</div>
    </main>
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* 侧边栏 */
.sidebar {
  width: 260px;
  min-width: 260px;
  background: #fff;
  border-right: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
}
.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid #f1f5f9;
}
.brand {
  font-weight: 700;
  color: #1f2d3d;
}
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}
.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  color: #334155;
  font-size: 14px;
}
.session-item:hover {
  background: #f1f5f9;
}
.session-item.active {
  background: #eef4ff;
  color: #1677ff;
}
.session-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.del-btn {
  opacity: 0;
}
.session-item:hover .del-btn {
  opacity: 1;
}
.empty {
  text-align: center;
  color: #94a3b8;
  font-size: 13px;
  padding: 24px 0;
}
.sidebar-footer {
  border-top: 1px solid #f1f5f9;
  padding: 12px 16px;
}
.user-line {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #334155;
  margin-bottom: 8px;
}
.footer-actions {
  display: flex;
  justify-content: space-between;
}

/* 主区 */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.chat-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}
.message-list {
  max-width: 860px;
  margin: 0 auto;
}
.welcome {
  text-align: center;
  color: #94a3b8;
  padding-top: 80px;
}
.welcome-icon {
  font-size: 48px;
}
.msg-row {
  display: flex;
  margin-bottom: 16px;
}
.msg-row.user {
  justify-content: flex-end;
}
.bubble {
  max-width: 78%;
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
}
.msg-row.user .bubble {
  background: #1677ff;
  color: #fff;
  border-bottom-right-radius: 4px;
}
.msg-row.assistant .bubble {
  background: #fff;
  color: #1f2d3d;
  border: 1px solid #e5e7eb;
  border-bottom-left-radius: 4px;
}
.bubble.emergency {
  background: #fef2f2 !important;
  color: #b91c1c !important;
  border: 1px solid #fecaca !important;
  font-weight: 600;
}
.bubble.error {
  background: #fef2f2 !important;
  color: #b91c1c !important;
  border: 1px solid #fecaca !important;
}

.typing {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}
.typing span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #cbd5e1;
  animation: blink 1.2s infinite;
}
.typing span:nth-child(2) {
  animation-delay: 0.2s;
}
.typing span:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes blink {
  0%, 80%, 100% { opacity: 0.2; }
  40% { opacity: 1; }
}

.sources {
  margin-top: 10px;
  font-size: 12px;
  color: #64748b;
}
.sources summary {
  cursor: pointer;
  color: #1677ff;
}
.sources ul {
  margin: 8px 0 0;
  padding-left: 16px;
}
.src-text {
  display: block;
  color: #94a3b8;
  margin-top: 2px;
}
.rate-row {
  margin-top: 8px;
  display: flex;
  gap: 4px;
}

.input-bar {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  padding: 12px 24px;
  border-top: 1px solid #e5e7eb;
  background: #fff;
  max-width: 860px;
  width: 100%;
  margin: 0 auto;
}
.send-btn {
  height: 56px;
}
.disclaimer {
  text-align: center;
  font-size: 12px;
  color: #94a3b8;
  padding: 4px 0 12px;
  background: #fff;
}
</style>