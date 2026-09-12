<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { getStats, type SystemStats } from '@/api/stats'

const router = useRouter()
const auth = useAuthStore()

const isAdmin = computed(() => auth.isAdmin)
const stats = ref<SystemStats | null>(null)

onMounted(async () => {
  auth.restore()
  if (isAdmin.value) await loadStats()
})

async function loadStats() {
  try {
    stats.value = await getStats()
  } catch {
    /* 统计加载失败不阻塞首页 */
  }
}

function enterChat() {
  router.push('/chat')
}

function enterAdmin(tab = '') {
  router.push({ path: '/admin', query: tab ? { tab } : {} })
}
</script>

<template>
  <div class="home">
    <div class="hero-card">
      <div class="logo">💊</div>
      <h1 class="title">医疗安全问答系统</h1>
      <p class="subtitle">基于 RAG + Agent 的用药安全智能问答，急症自动拦截、回答可溯源</p>

      <div class="features">
        <div class="feature">
          <div class="feature-icon">🛡️</div>
          <div class="feature-name">急症护栏</div>
          <div class="feature-desc">识别胸痛/昏迷等急症，立即引导就医</div>
        </div>
        <div class="feature">
          <div class="feature-icon">📚</div>
          <div class="feature-name">引用溯源</div>
          <div class="feature-desc">每个结论标注来源，拒绝编造</div>
        </div>
        <div class="feature">
          <div class="feature-icon">🧪</div>
          <div class="feature-name">相互作用检测</div>
          <div class="feature-desc">多药联用风险等级智能判断</div>
        </div>
      </div>

      <el-button type="primary" size="large" round @click="enterChat">
        开始咨询
      </el-button>
      <el-button v-if="isAdmin" text type="primary" @click="enterAdmin()">
        进入管理后台
      </el-button>
      <div class="guest-hint">未登录可先以游客身份体验</div>

      <div v-if="isAdmin" class="dashboard">
        <div class="dash-item dash-pending" @click="enterAdmin('review')">
          <div class="dash-value">{{ stats?.review?.pending ?? 0 }}</div>
          <div class="dash-label">待审核争议</div>
          <div class="dash-go">点击前往 →</div>
        </div>
        <div class="dash-item">
          <div class="dash-value">{{ stats?.vector_docs ?? 0 }}</div>
          <div class="dash-label">知识文档数</div>
        </div>
        <div class="dash-item">
          <div class="dash-value">{{ stats?.feedback?.dislikes ?? 0 }}</div>
          <div class="dash-label">累计点踩</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.home {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(160deg, #eef4ff 0%, #f7fbff 55%, #ecfdf5 100%);
  padding: 24px;
}
.hero-card {
  background: #fff;
  border-radius: 20px;
  box-shadow: 0 20px 60px rgba(23, 101, 255, 0.12);
  padding: 48px 56px;
  text-align: center;
  max-width: 640px;
  width: 100%;
}
.logo {
  font-size: 56px;
  margin-bottom: 8px;
}
.title {
  font-size: 30px;
  font-weight: 700;
  margin: 0 0 8px;
  color: #1f2d3d;
}
.subtitle {
  color: #64748b;
  font-size: 15px;
  margin: 0 0 28px;
}
.features {
  display: flex;
  gap: 16px;
  justify-content: center;
  margin-bottom: 28px;
  flex-wrap: wrap;
}
.feature {
  flex: 1;
  min-width: 140px;
  background: #f8fafc;
  border-radius: 12px;
  padding: 16px 12px;
}
.feature-icon {
  font-size: 26px;
}
.feature-name {
  font-weight: 600;
  margin: 8px 0 4px;
  color: #1f2d3d;
}
.feature-desc {
  font-size: 12px;
  color: #94a3b8;
}
.guest-hint {
  margin-top: 14px;
  font-size: 12px;
  color: #94a3b8;
}
.dashboard {
  display: flex;
  gap: 12px;
  margin-top: 20px;
}
.dash-item {
  flex: 1;
  background: #f8fafc;
  border-radius: 12px;
  padding: 14px 10px;
}
.dash-value {
  font-size: 26px;
  font-weight: 700;
  color: #1f2d3d;
}
.dash-label {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 4px;
}
.dash-pending {
  background: #fef2f2;
  border: 1px solid #fecaca;
  cursor: pointer;
}
.dash-pending .dash-value {
  color: #dc2626;
}
.dash-go {
  font-size: 11px;
  color: #dc2626;
  margin-top: 4px;
}
</style>