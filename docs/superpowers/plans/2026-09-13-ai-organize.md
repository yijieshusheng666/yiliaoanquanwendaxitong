# AI 智能整理导入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让管理员粘贴 TXT 药品说明书原文，由 LLM 自动整理成标准【章节】模板，经确认（可编辑）后才入库。

**Architecture:** 「AI 整理」端点 `organize` 只返回整理文本、不落库；整理文本填入前端编辑区，保存仍走现有 `upsert`（含格式校验）。离线模式（无 `LLM_API_KEY`）前端禁用 + 后端 400 双保险。

**Tech Stack:** FastAPI、LangChain ChatOpenAI、Vue3 + Element Plus、TypeScript

---

### Task 1: `app/core/document_organizer.py`

**Files:**
- Create: `app/core/document_organizer.py`

- [ ] **Step 1: 创建模块**，核心函数 `organize_to_template(raw_text) -> str`：

```python
"""把药品说明书原文用 LLM 整理成标准【章节】模板文本。"""
from __future__ import annotations

from app.config import ONLINE_MODE
from app.core.llm_provider import get_llm

# 允许的章节名白名单（对应 admin_routes.SECTION_WHITELIST）与整理要求
ORGANIZE_PROMPT = """你是一名专业的药品说明书整理员。请把下列【原文】整理成标准化的药品说明书模板，用于知识库入库。

整理要求：
1. 严格按下述章节顺序与章节名组织，只保留原文中出现的信息：
   【成分】【性状】【适应症】【用法用量】【不良反应】【禁忌】【注意事项】
   【特殊人群用药】【药物相互作用】【药物过量】【药物相容性】【贮藏】【有效期】
2. 内容必须忠于原文，不得编造、不得补充原文没有的信息；某一章节原文未涉及则整段省略。
3. 【药物相互作用】每条写成一行，格式：药品名（风险：高/中/低）：描述；多条用 "。；" 分隔；
   原文未给出风险等级时，可省略风险标注但保留 "药品名：描述"。
4. 只输出整理后的模板文本本身，不要输出任何开头语、说明或 Markdown 代码块围栏。

【原文】
{raw}
"""


def organize_to_template(raw_text: str) -> str:
    """Return 整理后的标准模板文本；离线或 LLM 失败时抛 RuntimeError。"""
    if not ONLINE_MODE:
        raise RuntimeError("当前为离线模式，需配置 LLM_API_KEY 才可使用 AI 智能整理")
    llm = get_llm()
    prompt = ORGANIZE_PROMPT.format(raw=(raw_text or "").strip()[:6000])
    out = llm.invoke(prompt)
    text = (getattr(out, "content", None) or "").strip()
    if not text:
        raise RuntimeError("LLM 未返回有效整理内容，请重试")
    return text
```

- [ ] **Step 2: 语法校验**

Run: `python -c "import ast; ast.parse(open('app/core/document_organizer.py',encoding='utf-8').read())"`
Expected: 无输出（通过）

### Task 2: `admin_routes.py` 新增 organize 端点

**Files:**
- Modify: `app/api/admin_routes.py`（新增 model + 端点，放在 template 端点之后、`/documents/{name}` 之前）

- [ ] **Step 1: 加 model**（放 `DocumentUpsert` 定义旁）：

```python
class DocumentOrganize(BaseModel):
    raw_text: str
```

- [ ] **Step 2: 加端点**（`document_template` 之后、`document_preview` 之前）：

```python
@router.post("/documents/organize")
async def organize_document(req: DocumentOrganize, user: dict = Depends(require_admin)):
    from app.config import ONLINE_MODE
    if not ONLINE_MODE:
        return JSONResponse(status_code=400,
                            content={"detail": "当前为离线模式，需配置 LLM_API_KEY 才可使用 AI 整理"})
    raw = (req.raw_text or "").strip()
    if not raw:
        return JSONResponse(status_code=400, content={"detail": "原文为空，请粘贴说明书文本"})
    from app.core.document_organizer import organize_to_template
    try:
        organized = await run_in_threadpool(organize_to_template, raw)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"detail": f"AI 整理失败：{exc}"})
    return {"organized": organized}
```

- [ ] **Step 3: 语法校验**（同上捕获，且确认 `import ast`）

### Task 3: 前端 API

**Files:**
- Modify: `frontend/src/api/admin.ts`

- [ ] **Step 1: 新增类型与函数**：

```ts
export interface OrganizeResult {
  organized: string
}

export function organizeDocument(rawText: string) {
  return api.post<OrganizeResult>('/api/admin/documents/organize', { raw_text: rawText })
}
```

### Task 4: `frontend/src/views/AdminView.vue` AI 整理面板

**Files:**
- Modify: `frontend/src/views/AdminView.vue`

- [ ] **Step 1: script 加状态与函数**（`ref` 区加 `rawText`、`organizing`、`onlineMode`；`onMounted` 拉 stats 设 `onlineMode`）：

```ts
const rawText = ref('')
const organizing = ref(false)
const onlineMode = ref(true)

// onMounted 中：先按现有逻辑校验 admin，再：
try {
  const st = await getStats()
  onlineMode.value = st.mode === 'online'
} catch { /* 忽略，默认在线 */ }

async function doOrganize() {
  if (!rawText.value.trim()) return ElMessage.warning('请先粘贴药品说明书原文')
  organizing.value = true
  try {
    const res = await adminApi.organizeDocument(rawText.value)
    docContent.value = res.organized
    ElMessage.success('已生成整理结果，请确认后点击「保存文档」')
  } catch (e) {
    ElMessage.error((e as Error).message || 'AI 整理失败')
  } finally {
    organizing.value = false
  }
}
```

- [ ] **Step 2: 模板加入 AI 整理区块**（放在「载入模板」所在面板之上，新建一个面板）：

```html
<section class="panel">
  <h3 class="panel-title">AI 智能整理导入</h3>
  <el-input v-model="rawText" type="textarea" :rows="6"
    placeholder="粘贴药品说明书 TXT 原文，一键用大模型整理成标准章节格式" />
  <div class="panel-actions">
    <el-tooltip :disabled="onlineMode" content="当前为离线模式，需配置 LLM_API_KEY 后启用">
      <span>
        <el-button type="success" :loading="organizing" :disabled="!onlineMode"
          @click="doOrganize">AI 智能整理</el-button>
      </span>
    </el-tooltip>
    <el-button @click="rawText = ''">清空原文</el-button>
  </div>
  <p class="hint">整理结果会填入下方编辑区，供你确认与修改；只有点击「保存文档」才会真正入库。</p>
</section>
```

- [ ] **Step 3: 新 `<section class="panel">` 需作为独立块**，放在「新增 / 更新文档」面板之前。

### Task 5: 验证

- [ ] **Step 1: 前端类型检查 + 构建**

Run: `cd frontend && npm run build`
Expected: vue-tsc 与 vite build 均通过

- [ ] **Step 2: 后端离线行为（语法已校验）**——离线配置下请求 organize 应 400

Run: 起后端（`LLM_API_KEY` 未配置），`POST /api/admin/documents/organize` 带任意 text
Expected: `400 {"detail":"当前为离线模式，需配置 LLM_API_KEY 才可使用 AI 整理"}`

### Task 6: 提交

- [ ] **Step 1: commit**

```bash
git add app/core/document_organizer.py app/api/admin_routes.py frontend/src/api/admin.ts frontend/src/views/AdminView.vue docs/superpowers/specs/2026-09-13-ai-organize-design.md
git commit -m "feat: AI 智能整理导入 — 大模型按标准模板整理药品说明书，确认后入库"
```

## 范围外
PDF/OCR 预处理、自动重建索引、JSON 结构化展示（见 spec「范围外」）。