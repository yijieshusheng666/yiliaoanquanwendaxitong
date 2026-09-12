<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, Refresh } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import * as adminApi from '@/api/admin'
import type { DocItem, DocSection, IndexVersion, ReviewItem } from '@/api/admin'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const activeTab = ref('docs')

// 文档管理
const docs = ref<DocItem[]>([])
const loadingDocs = ref(false)
const docName = ref('')
const docContent = ref('')
const fileInput = ref<HTMLInputElement>()
const previewVisible = ref(false)
const preview = ref<{ name: string; chunk_count: number; sections: DocSection[] } | null>(null)

// 索引管理
const idxReady = ref(false)
const idxCurrent = ref<IndexVersion | null>(null)
const idxVersions = ref<IndexVersion[]>([])
const idxDir = ref('')
const loadingIdx = ref(false)
const rebuilding = ref(false)

// 反馈审核
const reviews = ref<ReviewItem[]>([])
const reviewSummary = ref<Record<string, number>>({})
const reviewFilter = ref('pending')
const reviewLoading = ref(false)
const reviewDialog = ref(false)
const reviewForm = reactive({ id: 0, status: 'resolved', note: '', drug: '', content: '', question: '', answer: '' })

onMounted(async () => {
  auth.restore()
  if (!auth.isAdmin) {
    ElMessage.warning('需要管理员权限')
    router.replace('/')
    return
  }
  const tab = route.query.tab
  if (tab === 'review' || tab === 'index' || tab === 'docs') activeTab.value = tab
  await Promise.all([refreshDocs(), refreshIndex(), refreshReviews()])
})

async function refreshDocs() {
  loadingDocs.value = true
  try {
    const res = await adminApi.listDocuments()
    docs.value = res.documents
  } finally {
    loadingDocs.value = false
  }
}

async function refreshIndex() {
  loadingIdx.value = true
  try {
    const res = await adminApi.getIndexState()
    idxReady.value = res.ready
    idxCurrent.value = res.current
    idxVersions.value = res.versions
    idxDir.value = res.dir
  } finally {
    loadingIdx.value = false
  }
}

function pickFile() {
  fileInput.value?.click()
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  if (!f) return
  docName.value = f.name.replace(/\.txt$/i, '')
  const reader = new FileReader()
  reader.onload = () => {
    docContent.value = String(reader.result ?? '')
  }
  reader.readAsText(f)
  input.value = ''
}

async function saveDoc() {
  const name = docName.value.trim()
  if (!name) return ElMessage.warning('请填写药品名')
  if (!docContent.value.trim()) return ElMessage.warning('请填写或读取说明书内容')
  const res = await adminApi.upsertDocument(name, docContent.value)
  ElMessage.success(res.existed ? `已更新「${name}」，记得重建索引` : `已新增「${name}」，记得重建索引`)
  await refreshDocs()
}

async function openPreview(row: DocItem) {
  preview.value = await adminApi.previewDocument(row.name)
  previewVisible.value = true
}

async function removeDoc(row: DocItem) {
  try {
    await ElMessageBox.confirm(`确认删除文档「${row.name}」？删除后需重建索引。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await adminApi.deleteDocument(row.name)
  ElMessage.success(`已删除「${row.name}」`)
  await refreshDocs()
}

async function doRebuild() {
  try {
    await ElMessageBox.confirm(
      '重建索引会调用嵌入模型全量重算，耗时较长，是否继续？',
      '重建确认',
      { type: 'warning', confirmButtonText: '重建', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  rebuilding.value = true
  try {
    const res = await adminApi.rebuildIndex()
    ElMessage.success(`重建完成，共 ${res.chunk_count} 个分块`)
    await refreshIndex()
  } catch (e) {
    ElMessage.error((e as Error).message || '重建失败')
  } finally {
    rebuilding.value = false
  }
}

async function doRollback() {
  try {
    await ElMessageBox.confirm('回滚到上一版本索引？', '回滚确认', { type: 'warning' })
  } catch {
    return
  }
  const res = await adminApi.rollbackIndex()
  ElMessage.success(`已回滚到 ${res.current}`)
  await refreshIndex()
}

async function refreshReviews() {
  reviewLoading.value = true
  try {
    const res = await adminApi.listReviews(reviewFilter.value)
    reviews.value = res.reviews
    reviewSummary.value = res.summary
  } finally {
    reviewLoading.value = false
  }
}

function openReview(row: ReviewItem) {
  reviewForm.id = row.id
  reviewForm.status = 'resolved'
  reviewForm.note = ''
  reviewForm.drug = ''
  reviewForm.content = ''
  reviewForm.question = row.question
  reviewForm.answer = row.answer
  reviewDialog.value = true
}

async function submitReview() {
  const res = await adminApi.resolveReview(reviewForm.id, {
    status: reviewForm.status,
    note: reviewForm.note,
    drug: reviewForm.drug,
    content: reviewForm.content,
  })
  ElMessage.success(res.reflowed ? '已处理，纠错知识已回流（记得重建索引）' : '已处理')
  reviewDialog.value = false
  await refreshReviews()
}

function fmtTime(t: number) {
  return new Date(t * 1000).toLocaleString()
}

function fmtSize(n: number) {
  return n > 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} B`
}
</script>

<template>
  <div class="admin">
    <header class="admin-header">
      <div class="admin-title">知识库管理后台</div>
      <div class="admin-actions">
        <el-button text @click="router.push('/')">返回首页</el-button>
        <el-button text @click="router.push('/chat')">返回问答</el-button>
      </div>
    </header>

    <el-tabs v-model="activeTab" class="admin-tabs">
      <el-tab-pane label="文档管理" name="docs">
        <section class="panel">
          <h3 class="panel-title">新增 / 更新文档</h3>
          <div class="upload-row">
            <input
              ref="fileInput"
              type="file"
              accept=".txt,text/plain"
              style="display: none"
              @change="onFileChange"
            />
            <el-button :icon="Upload" @click="pickFile">从文件读取</el-button>
            <el-input v-model="docName" placeholder="药品名（如 阿莫西林）" class="name-input" />
          </div>
          <el-input
            v-model="docContent"
            type="textarea"
            :rows="8"
            placeholder="粘贴说明书文本，按【章节】结构化，例如：【适应症】…【用法用量】…"
          />
          <div class="panel-actions">
            <el-button type="primary" @click="saveDoc">保存文档</el-button>
            <el-button @click="docName = ''; docContent = ''">清空</el-button>
          </div>
          <p class="hint">文件名即为药品名。保存后需到「索引管理」点击重建，改动才会进入检索。</p>
        </section>

        <el-table v-loading="loadingDocs" :data="docs" border stripe>
          <el-table-column prop="name" label="药品名" min-width="160" />
          <el-table-column prop="chunks" label="分块数" width="90" align="center" />
          <el-table-column label="大小" width="110" align="center">
            <template #default="{ row }">{{ fmtSize(row.size) }}</template>
          </el-table-column>
          <el-table-column label="更新时间" width="180">
            <template #default="{ row }">{{ fmtTime(row.updated_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="140" align="center">
            <template #default="{ row }">
              <el-button link type="primary" @click="openPreview(row)">预览</el-button>
              <el-button link type="danger" @click="removeDoc(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="索引管理" name="index">
        <section class="panel">
          <div class="idx-status">
            <el-tag :type="idxReady ? 'success' : 'danger'">{{ idxReady ? '就绪' : '缺失' }}</el-tag>
            <span class="idx-dir">{{ idxDir }}</span>
          </div>
          <div class="panel-actions">
            <el-button type="primary" :icon="Refresh" :loading="rebuilding" @click="doRebuild">
              重建索引
            </el-button>
            <el-button :disabled="idxVersions.length < 2" @click="doRollback">回滚上一版本</el-button>
            <el-button @click="refreshIndex">刷新</el-button>
          </div>
          <p class="hint">重建采用版本化流程，失败自动回滚；重建后检索立即生效，无需重启服务。</p>
        </section>

        <el-table v-loading="loadingIdx" :data="idxVersions" border stripe>
          <el-table-column prop="name" label="版本" width="130" />
          <el-table-column label="分块数" width="100" align="center">
            <template #default="{ row }">{{ row.stats?.chunk_count ?? '-' }}</template>
          </el-table-column>
          <el-table-column prop="built_at" label="构建时间" width="200" />
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="idxCurrent?.name === row.name ? 'success' : 'info'" size="small">
                {{ idxCurrent?.name === row.name ? '当前' : row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="path" label="路径" min-width="220" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="反馈审核" name="review">
        <section class="panel">
          <div class="review-filter">
            <el-radio-group v-model="reviewFilter" @change="refreshReviews">
              <el-radio-button label="pending">待处理</el-radio-button>
              <el-radio-button label="resolved">已解决</el-radio-button>
              <el-radio-button label="ignored">已忽略</el-radio-button>
            </el-radio-group>
            <span class="review-summary">
              待处理 {{ reviewSummary.pending ?? 0 }} · 已解决 {{ reviewSummary.resolved ?? 0 }} · 已忽略 {{ reviewSummary.ignored ?? 0 }}
            </span>
          </div>
        </section>

        <el-table v-loading="reviewLoading" :data="reviews" border stripe>
          <el-table-column prop="id" label="ID" width="70" align="center" />
          <el-table-column label="问题" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">{{ row.question }}</template>
          </el-table-column>
          <el-table-column label="原回答" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">{{ row.answer }}</template>
          </el-table-column>
          <el-table-column prop="count" label="点踩数" width="90" align="center" />
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag
                :type="row.status === 'pending' ? 'danger' : row.status === 'resolved' ? 'success' : 'info'"
                size="small"
              >
                {{ row.status === 'pending' ? '待处理' : row.status === 'resolved' ? '已解决' : '已忽略' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="审核" width="170" align="center">
            <template #default="{ row }">
              <div
                v-if="row.status !== 'pending'"
                class="review-cell"
                :title="row.note || ''"
              >
                <div>{{ row.reviewed_by || '-' }}</div>
                <div class="review-cell-time">{{ row.reviewed_at ? fmtTime(row.reviewed_at) : '' }}</div>
              </div>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100" align="center">
            <template #default="{ row }">
              <el-button v-if="row.status === 'pending'" link type="primary" @click="openReview(row)">
                处理
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="previewVisible"
      :title="`文档预览：${preview?.name ?? ''}`"
      width="720px"
      top="6vh"
    >
      <div v-if="preview" class="preview">
        <p class="preview-meta">共 {{ preview.chunk_count }} 个分块，{{ preview.sections.length }} 个章节</p>
        <div v-for="s in preview.sections" :key="s.section" class="preview-section">
          <div class="preview-section-name">【{{ s.section }}】</div>
          <div class="preview-section-text">{{ s.text }}</div>
        </div>
      </div>
    </el-dialog>

    <el-dialog v-model="reviewDialog" title="处理争议问题" width="620px" top="8vh">
      <div class="review-dialog">
        <div class="review-context">
          <div class="review-context-q"><span class="label">问题</span>{{ reviewForm.question }}</div>
          <div class="review-context-a"><span class="label">原回答</span>{{ reviewForm.answer }}</div>
        </div>
        <el-radio-group v-model="reviewForm.status">
          <el-radio label="resolved">标记已解决</el-radio>
          <el-radio label="ignored">忽略（无需处理）</el-radio>
        </el-radio-group>
        <el-input
          v-model="reviewForm.note"
          type="textarea"
          :rows="3"
          placeholder="审核备注（可选）"
          class="review-note"
        />
        <el-divider content-position="left">回流知识库（可选）</el-divider>
        <el-input v-model="reviewForm.drug" placeholder="目标药品名（如 阿莫西林）" class="review-note" />
        <el-input
          v-model="reviewForm.content"
          type="textarea"
          :rows="4"
          placeholder="纠错后补充的知识内容，将作为【人工审核补充】追加到该药品文档"
          class="review-note"
        />
        <p class="hint">填写药品名与内容后，会追加到对应文档；随后需重建索引才会进入检索。</p>
      </div>
      <template #footer>
        <el-button @click="reviewDialog = false">取消</el-button>
        <el-button type="primary" @click="submitReview">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.admin {
  min-height: 100vh;
  background: #f5f7fa;
  padding: 20px 32px;
}
.admin-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.admin-title {
  font-size: 20px;
  font-weight: 700;
  color: #1f2d3d;
}
.admin-tabs {
  max-width: 1080px;
  margin: 0 auto;
}
.panel {
  background: #fff;
  border-radius: 10px;
  padding: 20px;
  margin-bottom: 16px;
}
.panel-title {
  margin: 0 0 16px;
  font-size: 15px;
  color: #1f2d3d;
}
.upload-row {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}
.name-input {
  max-width: 320px;
}
.panel-actions {
  margin-top: 14px;
  display: flex;
  gap: 10px;
}
.hint {
  margin: 12px 0 0;
  font-size: 12px;
  color: #94a3b8;
}
.idx-status {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}
.idx-dir {
  font-size: 13px;
  color: #64748b;
  word-break: break-all;
}
.preview-meta {
  color: #64748b;
  font-size: 13px;
  margin: 0 0 12px;
}
.preview-section {
  margin-bottom: 14px;
}
.preview-section-name {
  font-weight: 600;
  color: #1f2d3d;
  margin-bottom: 4px;
}
.preview-section-text {
  font-size: 13px;
  color: #475569;
  line-height: 1.6;
  white-space: pre-wrap;
}
.review-context {
  background: #f8fafc;
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 14px;
  font-size: 13px;
  color: #334155;
  line-height: 1.6;
  max-height: 140px;
  overflow-y: auto;
}
.review-context .label {
  color: #94a3b8;
  font-weight: 600;
  margin-right: 6px;
}
.review-context-q {
  margin-bottom: 6px;
}
.review-cell {
  font-size: 12px;
  line-height: 1.4;
}
.review-cell-time {
  color: #94a3b8;
  font-size: 11px;
}
.review-filter {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.review-summary {
  font-size: 13px;
  color: #64748b;
}
.review-note {
  margin-top: 14px;
}
.review-dialog {
  max-height: 60vh;
  overflow-y: auto;
}
</style>