# AI 智能整理导入设计

日期：2026-09-13　状态：已批准

## 背景与目标

管理后台「文档管理」目前只能手动「载入模板 + 编辑 + 保存」。管理员拿到一份药品说明书原文时，需手工按标准章节整理，效率低且易失误。

目标：提供「AI 智能整理」入口——上传/粘贴 TXT 原文，由大模型按标准模板结构化，管理员确认（可编辑）后才入库。

## 决策（已与用户确认）

- 输入格式：**TXT / 纯文本**（本期不做 PDF/OCR）。
- 确认交互：**预览 + 可编辑 + 批准才保存**。整理只产预览文本，绝不写库；保存仍走现有 `upsert`（含格式校验）。
- 离线降级：`ONLINE_MODE=False`（未配 `LLM_API_KEY`）时，入口**禁用并提示需在线模式**；同时后端也返回 400 双保险。

## 核心原则

「AI 整理」与「保存」彻底分离：
- `organize` 端点只返回整理后的文本，不落盘。
- 只有管理员点击「保存文档」才触发 `upsert` → 格式校验 → 写 `data/texts/*.txt`。
- AI 整理产物流入同一个编辑区 `docContent`，与「载入模板」并存，是加速捷径而非替代。

## 组件与数据流

```
管理员粘贴 TXT 原文
  → POST /api/admin/documents/organize  {raw_text}
      → 校验 ONLINE_MODE（离线返回 400「需在线模式」）
      → document_organizer.organize_to_template(raw_text)  （run_in_threadpool 跑同步 LLM）
      → 返回 {organized: "标准模板文本"}（不落库）
  → 前端填入可编辑区 docContent
  → 管理员可手动改 → 点「保存文档」
      → upsert（格式校验 + 写入 data/texts → 手动重建索引）
```

### 1. `app/core/document_organizer.py`（新增）

`organize_to_template(raw_text: str) -> str`
- 构造整理 prompt：按标准章节组织（适应症/用法用量/不良反应/禁忌/注意事项/特殊人群用药/药物相互作用/贮藏等，见 `admin_routes.SECTION_WHITELIST`）；不得编造、原文缺失的章节省略；【药物相互作用】保留 `药名（风险：高/中/低）：描述` 格式；只输出模板文本，不输出解释。
- 调用 `llm_provider.get_llm()`；输出为空或异常 → 抛 `RuntimeError`。
- `from app.config import ONLINE_MODE`；`not ONLINE_MODE` 时直接抛「需在线模式」，作为离线双保险。

### 2. `app/api/admin_routes.py`（改动）

新增 `POST /api/admin/documents/organize`：
- body：`class DocumentOrganize(BaseModel): raw_text: str`
- `raw_text` 空白 → 400「原文为空」
- `not ONLINE_MODE` → 400「需在线模式，无法使用 AI 整理」
- `run_in_threadpool(organize_to_template, raw_text)`；异常 → 400 透出消息
- 返回 `{"organized": text}`
- 路由路径 `/documents/organize` 为 POST，与 `/documents/{name}`（GET/DELETE）不冲突。

### 3. 前端 `frontend/src/views/AdminView.vue`（改动）

「文档管理」面板新增「AI 智能整理」区块：
- 一个 textarea 粘贴源文本 + 「AI 智能整理」按钮。
- 整理结果写入下方正式编辑区 `docContent`（可继续编辑）。
- `onMounted` 拉 `/api/stats` 得 `onlineMode = mode === 'online'`；`!onlineMode` 时按钮 `disabled` + tooltip「需在线模式」。
- `frontend/src/api/admin.ts` 新增 `organizeDocument(raw_text)` 与类型。

## 错误处理

| 场景 | 行为 |
|---|---|
| 离线（无 LLM_API_KEY） | 前端禁用按钮 + 后端返回 400「需在线模式」 |
| 原文为空 | 后端 400「原文为空」 |
| LLM 超时/异常/空输出 | 后端 400 透出消息，前端 toast |
| 整理结果章节不合规 | 前端提示继续编辑或重试；保存时仍会过格式校验兜底 |

## 测试

- 端点级（无需真 LLM）：不 mock 时验证 `ONLINE_MODE=False` → `organize` 返回 400「需在线模式」。
- 集成：真实在线模式整理一段样例说明书，结果 `validate_doc_content` 应无 error（或至少结构闭合）。
- 前端：`vue-tsc` 类型检查 + `vite build` 通过。

## 范围外（本期不做）

- PDF / 扫描件 OCR 预处理。
- 自动重建索引（确认后仍由管理员显式触发）。
- 整理结果的结构化 JSON 展示（本期直接产出模板文本）。