# 医疗安全问答系统（RAG + Agent 企业级实践）

基于 **RAG + Agent 混合检索架构**的用药安全问答系统，专注回答三类高频用药问题：**药物能不能一起吃、特定人群能不能吃、具体怎么吃**。每条回答有据可查（引用溯源 + 合法性校验），安全合规（急症拦截 + 免责声明），并配套**管理后台（知识库治理 + 反馈闭环）**与**可量化评测体系**，是面向企业级落地的大模型垂直领域实践。

## ✨ 核心能力

### 问答主链路
| 功能 | 说明 |
|---|---|
| 💬 用药问答 | 自然语言提问 → 混合检索知识库 → 生成带 `[n]` 引用编号的回答 |
| 🩺 病症荐药 | 说出病症（如"发烧吃什么药"）→ 综合推荐全部治疗方案（提示词强制不遗漏） |
| 🔬 混合检索 | **BM25 稀疏 + 向量稠密双路召回 + RRF 融合**，专名/药名命中率显著优于纯向量检索 |
| 🎯 CrossEncoder 重排 | bge-reranker-base 精排候选分块，压制噪声提升相关性（可开关、缺失时透明降级） |
| 📚 来源轮转均衡 | 检索结果按药品名分组轮转抽取，避免结果集中在少数药品 |
| 📖 引用溯源 + 校验 | 关键结论标注引用编号；回答的 `[n]` 引用必须锚定到真实来源药名，失败则降级提示 |
| 🚨 急症护栏 | 命中胸痛/昏迷/自杀/中毒/大出血等急症关键词 → 直接返回「拨打 120」，不做生成 |
| 📉 置信度门控 | top-1 相关度低于阈值（默认 0.35）判定未命中，拒绝用低分噪声作答 |
| ⚠️ 免责声明 | 每条回答末尾自动追加「仅供学习参考，不构成医疗建议」 |
| 🤝 相互作用专项 | 识别「A 和 B 能一起吃吗」→ ReAct Agent 调结构化 CSV 补充风险等级（高/中/低） |
| 💬 多轮对话 | 自动携带最近 3 轮上下文，支持追问（如「那和布洛芬一起吃呢？」） |

### 用户与反馈闭环
| 功能 | 说明 |
|---|---|
| 🔐 用户系统 | 独立登录/注册，密码 PBKDF2-HMAC-SHA256（随机盐 + 20 万次迭代）加密存储 |
| 🗂 多会话管理 | SQLite 持久化会话，登录后按账号隔离 |
| 🔄 登录态持久化 | localStorage 保存 token，刷新不掉线，退出真正吊销后端 token |
| 👍 满意度反馈 | 点赞/点踩写入 JSON Lines；**点踩自动进入争议审核队列** |
| 🔁 反馈闭环 | 点踩入队 → 管理员审核（resolved/ignored）→ 纠错知识回流药品文档 → 重建索引生效 |
| 🧑‍💼 管理后台 | 文档增删查（`data/texts`）、索引版本化重建/回滚、反馈审核与知识回流 |
| 📋 操作审计 | 管理员/用户关键操作写入审计日志（audit.db），可追溯 |

## 🏗️ 技术栈

| 层 | 选型 |
|---|---|
| 大模型 | DeepSeek 等 OpenAI 兼容接口（无 Key 自动切离线确定性演示模式） |
| 嵌入模型 | `bge-small-zh-v1.5`（本地 `models/`，CPU 推理） |
| 重排模型 | `bge-reranker-base`（CrossEncoder，本地 `models/`，可开关） |
| 稀疏检签 | `rank-bm25`（字符 bigram 分词） |
| 向量数据库 | Chroma（本地持续化于 **纯 ASCII 路径**，版本化治理，零服务依赖） |
| 框架 | LangChain（`<0.4`，ReAct Agent + 自定义流式检索链） |
| 后端 | FastAPI（异步 SSE 流式 + Swagger + 认证/管理路由） |
| 前端 | **Vue3 + TypeScript + Vite + Element Plus + Pinia + Vue Router** |
| 数据存储 | SQLite（会话/用户/审计/审核）+ JSON Lines（反馈） |

## 📁 项目结构

```
医疗安全问答系统/
├── app/
│   ├── config.py             # 全局配置（路径/模型/端口/检索阈值/安全文案）
│   ├── api/
│   │   ├── server.py         # FastAPI 入口：SSE 流式 + 认证 + 反馈 + 统计
│   │   ├── user_routes.py    # 用户认证（注册/登录/登出/me）+ require_admin 依赖
│   │   └── admin_routes.py   # 管理后台：文档 CRUD + 索引治理 + 反馈审核/知识回流
│   └── core/
│       ├── retrieval.py      # 混合检索（BM25+向量+RRF）+ 来源轮转 + 重排
│       ├── bm25_index.py     # BM25 稀疏索构建/持久化/检索（bigram 分词）
│       ├── rerank.py         # CrossEncoder 精排（透明降级）
│       ├── ingestion.py      # txt 解析 + 语义分块（携带药品名/章节元数据）
│       ├── index_versioning.py # 索引版本治理（MANIFEST + 指纹 + 原子切换/回滚）
│       ├── citation_guard.py # 引用合法性校验
│       ├── guardrails.py     # 急症护栏
│       ├── interaction_db.py # 相互作用 CSV（名称归一化 + O(1) 药对索引）
│       ├── service.py        # 问答编排：护栏→分类→检索→RAG/Agent→引用→免责
│       ├── feedback.py       # 反馈 JSON 记录
│       ├── review.py         # 反馈闭环：争议入队/状态管理/审核
│       ├── audit.py          # 操作审计
│       ├── auth.py / chat_history.py / offline.py / llm_provider.py / logging_setup.py
├── frontend/                 # Vue3 + Element Plus 单页应用（dev + build）
│   ├── src/views/            # HomeView / ChatView / LoginView / AdminView
│   ├── src/api/              # auth / chat / conversation / admin / stats / http
│   └── vite.config.ts        # /api 代理 → 127.0.0.1:8000
├── scripts/
│   ├── build_index.py        # 构建版本化向量索引
│   ├── download_model.py     # 下载 bge 嵌入模型
│   ├── download_reranker.py  # 下载 bge-reranker-base（HF镜像/ModelScope兜底）
│   ├── evaluate.py           # 六维离线评测（不依赖 LLM）
│   ├── eval_retrieval.py     # 检索 A/B：纯向量 vs 混合 召回率对比
│   ├── ragas_eval.py         # RAGAS 风格端到端评估（LLM-as-judge 四项指标）
│   └── init_data_v2 / build_drug_registry / reconcile_ddi / verify_knowledge / ocr_*
├── tests/                    # 10 个单元测试（pytest）：护栏/认证/检索/重排/审核/流式/索引治理…
├── data/
│   ├── texts/                # 102 份检索语料 txt（说明书 + 本草纲目）
│   ├── pdfs/                 # 说明书 PDF
│   ├── interactions.csv      # 385 对药物相互作用（含风险等级）
│   ├── test_set.json         # 评测测试集（常规 + 压力）
│   └── L0_sources…L4_eval/   # 分层数据管线
├── models/                   # 本地嵌入/重排模型
├── outputs/                  # SQLite(db) + 反馈(feedback.jsonl) + 评测报告
├── run.py / Dockerfile / docker-compose.yml / .env.example
└── requirements.txt
```

## 🚀 快速开始

### 1. 后端（FastAPI）

```bash
# 安装后端依赖（CPU 版 torch 减小体积）
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

# 配置大模型：复制 .env.example 为 .env 并填 LLM_API_KEY（不填则走离线演示模式）
copy .env.example .env

# 启动 API（首次自动生成数据 → 下载嵌入模型 → 构建索引）
python -m uvicorn app.api.server:app --host 0.0.0.0 --port 8000
```

- Swagger 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/health
- 接口：`/api/stats`、`/api/chat`、`/api/feedback`、`/api/admin/*` 等

### 2. 前端（Vue3）

```bash
cd frontend
npm install
npm run dev        # 开发：http://localhost:5173（/api 代理到 8000）
npm run build      # 生产构建 → dist/（可与后端/静态服务器一起部署）
```

> **索引路径**：向量库默认 `D:/medsafe_index`（纯 ASCII，避免 chroma-hnswlib 写中文路径报错）；可用环境变量 `INDEX_ROOT` / `CHROMA_DIR` 覆盖（Docker 部署指向容器内挂载路径）。

### 3. 重排模型（可选，推荐）

```bash
python scripts/download_reranker.py   # 下载 bge-reranker-base（~1.1GB，HF镜像/ModelScope兜底）
# .env 设置 RERANK_ENABLED=1
```

## 🔐 用户系统与管理后台

- **注册/登录**：独立认证页；注册成功即自动登录。
- **安全**：密码 PBKDF2-HMAC-SHA256（随机盐 16B + 20 万次迭代）；token 为 `secrets.token_urlsafe(32)`，库中仅存 SHA-256 摘要，7 天过期。
- **账号隔离**：登录后会话/历史/反馈按 `user_id` 隔离；未登录为游客（公共空间）。
- **管理后台**：管理员（`role=admin`）登录后从首页进入，含三个标签页：
  1. **文档管理**：上传/预览/删除 `data/texts` 药品文档
  2. **索引管理**：版本化重建 / 回滚，失败自动回退
  3. **反馈审核**：点踩入队的争议问题，标记 resolved（并回流纠错知识）或 ignored

## 🧪 评测体系

### 离线六维评测（确定性，不依赖 LLM）
```bash
python scripts/evaluate.py
```
| 指标 | 验收标准 |
|---|---|
| Top-3 召回率 | ≥ 85% |
| 急症拦截率 | = 100% |
| 引用准确率 | ≥ 90% |
| 回答忠实度 | ≥ 90% |
| 护栏误报率（压力） | = 0% |
| 路径准确率（压力） | = 100% |

### 检索 A/B 评测（对比检索策略召回）
```bash
python scripts/eval_retrieval.py
```

### RAGAS 风格端到端评估（LLM-as-judge 四项指标）
```bash
python scripts/ragas_eval.py --limit N            # 在线：忠实/相关/上下文精确/上下文召回
python scripts/ragas_eval.py --only-retrieval     # 仅检索侧（省成本，测 context_precision/recall）
```
> 自实现 judge，不引入 ragas 重依赖（避免拉高 langchain/pydantic 版本与 `<0.4` 约束冲突）。报告落盘 `outputs/ragas_eval.json`。

单元测试：`pytest tests/ -v`

## 📚 知识库治理

### 新增药物知识（四步）
```bash
# 1. data/texts/<药品名>.txt，内容按【章节】切分（适应症/用法用量/禁忌/注意事项/药物相互作用/特殊人群用药）
# 2. 质量校验
python scripts/verify_knowledge.py --new 药品名
# 3. 重建索引（版本化，语料指纹变化才重建；真实终端运行）
python scripts/build_index.py
# 4. 重启服务
```
> 也可直接在管理后台「文档管理」上传，「索引管理」重建，更便捷。

### 从 PDF 导入（OCR 流程）
```bash
python scripts/ocr_extract.py <name> <pdf路径>   # 扫描件 OCR → data/ocr_raw/<name>.txt
python scripts/parse_ocr.py                      # 解析为知识库 txt
python scripts/build_index.py && 重启
```

### 反馈闭环（知识自助回流）
点踩 → `/api/feedback` 自动入队（同问题去重计数）→ 管理后台「反馈审核」→ resolved 时以「人工审核补充」章节追加到文档 → 重建索引进入检索。全程审计留痕。

## 🔌 API 示例

```bash
# 流式问答（SSE）
curl -N -X POST http://127.0.0.1:8000/api/chat -H "Content-Type: application/json" \
  -d '{"question":"布洛芬和阿司匹林能一起吃吗？","stream":true}'

# 反馈（点踩自动入队审核）
curl -X POST http://127.0.0.1:8000/api/feedback -H "Content-Type: application/json" \
  -d '{"question":"...","answer":"...","rating":-1}'

# 统计（含待审核争议数）
curl http://127.0.0.1:8000/api/stats
```

## ⚠️ 项目边界

- ❌ 不提供疾病诊断、不制定个性化用药方案、不联网搜索、不支持语音/多模态
- ✅ 覆盖 102 份知识文本（说明书 + 本草纲目）+ 385 对药物相互作用 + 版本化向量索引
- ✅ 支持用户注册登录、多会话、反馈闭环、管理后台、操作审计
- 每条回答仅供学习参考，**不构成医疗建议**；急症请立即拨打 120

## 🔍 在线 / 离线模式

- 配置 `LLM_API_KEY` → **在线模式**：RAG 流式生成，相互作用走 ReAct Agent。
- 未配置 → **离线模式**：确定性模板回答（零成本、结果可复现），仅用于演示与评测。

## 🗺️ 演进方向

- 向量库 Chroma → Milvus/Qdrant（生产级、可水平扩展）
- SQLite → PostgreSQL（多实例共享状态）
- 全量 RAGAS 评估 + 检索回归门禁（召回率低于阈值 CI 阻断）
- 多副本无状态部署、监控指标（Prometheus `/metrics`）