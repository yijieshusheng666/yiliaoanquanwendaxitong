# 医疗安全问答系统（RAG + Agent）

基于 **RAG + Agent 架构**的医疗安全问答系统，专注回答三类高频用药问题：**药物能不能一起吃、特定人群能不能吃、具体怎么吃**。每条回答有据可查（带引用溯源）且安全合规（急症拦截 + 免责声明），用于展示大模型在垂直领域的工程化落地能力。

## ✨ 核心能力

| 功能 | 说明 |
|---|---|
| 💬 用药问答 | 自然语言提问 → RAG 检索全库知识 → 生成带 `[n]` 引用编号的回答 |
| 🩺 病症荐药 | 说出病症（如"发烧吃什么药"）→ 跨来源综合推荐所有治疗方案 |
| 📚 全库均衡检索 | 来源轮转抽取，药品说明书/处方集/指南/本草纲目**无优先级、一视同仁**，不偏重任何一本书 |
| 📖 引用溯源 | 关键结论标注引用编号，前端展示「药品名 · 章节」原文出处 |
| 🚨 安全护栏 | 命中胸痛/昏迷/自杀/中毒/大出血等急症关键词 → 直接返回「请立即拨打120」，不做任何生成 |
| ⚠️ 免责声明 | 每条回答末尾自动追加「仅供学习参考，不构成医疗建议」 |
| 🤝 相互作用专项 | 识别「A 和 B 能一起吃吗」→ ReAct Agent 调用结构化 CSV 补充风险等级（高/中/低） |
| 💬 多轮对话 | 每轮提问自动携带最近 3 轮上下文，支持追问（如「那和布洛芬一起吃呢？」） |
| 🗂 多会话管理 | SQLite 持久化会话，支持**新建对话 / 历史会话列表 / 删除对话**，刷新页面自动恢复最近会话 |
| 🎨 吉祥物 UI | 首页大机器人图标（CSS 动画）→ 点击进入聊天；机器人/用户头像均为此形象 |
| 👍 满意度评价 | 最新回复完成后下方出现「满意 / 不满意」，点击后即消失并写入本地 JSON Lines；下条新回复完成后再次出现 |

## 🏗️ 技术栈

- **大模型**：智谱 GLM-4-Flash（OpenAI 兼容接口，`open.bigmodel.cn`；无 Key 时自动进入离线确定性演示模式）
- **嵌入模型**：`bge-small-zh-v1.5`（本地 `models/` 加载，CPU 推理）
- **向量数据库**：Chroma（本地持久化于 **`D:/chroma_db`**，零服务依赖）
- **RAG/Agent 框架**：LangChain（`create_react_agent` + 自定义流式 RAG）
- **后端**：FastAPI（异步 SSE 流式输出 + Swagger 自动文档）
- **前端**：Gradio（首页吉祥物 + 聊天 UI + 引用溯源 + 满意度评价）
- **数据存储**：CSV（相互作用表）+ JSON（反馈）+ SQLite（会话历史 `outputs/chat_history.db`）
- **评测**：30 条人工标注测试集 + 自定义 Python 脚本计算指标

## 📁 项目结构

```
医疗安全问答系统/
├── app/
│   ├── config.py            # 全局配置（路径 / 模型 / 安全文案）
│   ├── api/server.py        # FastAPI：SSE 流式 + /docs + 满意度评价接口
│   ├── ui/gradio_app.py     # Gradio UI：首页机器人 + 聊天页 + 头像
│   ├── ui/static/           # bot_avatar.svg / user_avatar.svg 头像
│   ├── core/
│   │   ├── guardrails.py    # 急症护栏（规则拦截，100%）
│   │   ├── ingestion.py     # 说明书 txt 解析 + 语义分块（携带药品名/章节元数据）
│   │   ├── retrieval.py     # bge 嵌入 + Chroma 检索 + 来源轮转均衡
│   │   ├── interaction_db.py# 相互作用 CSV 查询（名称归一化 + O(1) 药对索引）
│   │   ├── chat_history.py   # 会话历史 SQLite 持久化（多会话：新建/列表/删除/恢复）
│   │   ├── offline.py       # 离线确定性回答器（演示/评测）
│   │   ├── service.py       # 问答编排：护栏→分类→RAG/Agent→引用→免责声明
│   │   ├── feedback.py      # 反馈 JSON 记录
│   │   └── llm_provider.py  # 大模型工厂（OpenAI 兼容接口）
│   └── data/
│       ├── generate_data.py # 生成 101 份说明书 PDF + interactions.csv + 测试集
│       └── real_interactions.py  # 真实 DDI（药典/DrugBank 整理）
├── scripts/
│   ├── download_model.py    # 下载 bge-small-zh-v1.5（HF镜像/ModelScope兜底）
│   ├── build_index.py       # 构建向量索引
│   ├── evaluate.py          # 评测脚本（六项指标）
│   ├── ocr_extract.py       # RapidOCR 批量抽取 PDF 文本
│   └── parse_ocr.py         # OCR 原始文本 -> 知识库 txt（处方集/指南）
├── tests/test_guardrails.py # 护栏单元测试
├── data/
│   ├── texts/               # 知识库 txt（权威输入，590 份：243 处方药 + 213 疾病章节 + 说明书 + 本草纲目）
│   ├── pdfs/                # 101 份说明书 PDF（演示产物）
│   ├── ocr_raw/             # OCR 原始文本（chufangji.txt / zhinan.txt）
│   ├── interactions.csv     # 941 对药物相互作用
│   └── test_set.json        # 30 条人工标注测试集
├── models/                  # 本地嵌入模型（运行时下载）
├── outputs/                 # 日志 / 反馈 / 评测报告
├── run.py                   # 一键启动
├── requirements.txt
├── Dockerfile / docker-compose.yml
└── .env.example
```

## 🚀 快速开始

### 方式一：本地运行

```bash
# 1. 安装依赖（推荐先装 CPU 版 torch 减小体积）
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

# 2. 配置大模型 Key：复制 .env.example 为 .env 并填入（默认可不填，走离线演示模式）
copy .env.example .env

# 3. 一键启动（自动生成数据 → 下载嵌入模型 → 构建索引 → 启动 API + UI）
python run.py
```

- Gradio UI：http://127.0.0.1:7860
- Swagger 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/health

> **注意**：向量库固定在 `D:/chroma_db`（纯 ASCII 路径，避免 chroma-hnswlib 写 HNSW 文件时中文路径报错）。
> 首次启动自动生成说明书 PDF、下载 bge 模型（约 100MB 到 `models/`）、构建索引。
> 国内网络 HuggingFace 不可达时自动回退 ModelScope 下载；也可 `python scripts/download_model.py`。

### 方式二：Docker Compose

```bash
docker compose up --build
```

访问同上。

## 🧪 评测（六项量化验收指标）

```bash
python scripts/evaluate.py
```

| 指标 | 定义 | 验收标准 |
|---|---|---|
| Top-3 召回率 | 检索 top3 命中测试题对应药品 | ≥ 85% |
| 回答忠实度 | 回答包含测试集标注的关键事实（自动启发式 + 人工抽检清单） | ≥ 90% |
| 急症拦截率 | 急症测试用例全部触发护栏 | 100% |
| 引用准确率 | 回答中 `[n]` 引用编号均对应真实来源 | ≥ 90% |
| 护栏误报率 | 诱饵题/否定语境（如"这不是心梗，是胃痛"）被护栏误拦的比例 | 越低越好 |
| 路径准确率 | Agent/RAG 路径选择与测试集标注 `expect_path` 一致的占比 | 越高越好 |

> 测试集含 30 条常规用例 + 6 条压力测试用例（诱饵题/边界模糊题/护栏诱饵），用于评估系统鲁棒性。
> 报告输出至 `outputs/eval_report.json`。单元测试：`pytest tests/ -v`。
> 评测默认走**确定性离线回答**（不依赖 LLM，结果可复现）；已配置 API Key 时也不影响指标。

## 📚 知识库

### 当前内置数据

- **知识库文本**：`data/texts/*.txt` 共 **590 份** —— 243 种处方药（国家基本药物处方集）+ 213 个疾病章节（国家基本药物临床应用指南·基层部分）+ 101 份说明书副本 + 《本草纲目》
- **药物相互作用**：`data/interactions.csv` 共 **941 对**（含整理自 DrugBank / 权威药典的公认真实 DDI）
- **向量索引**：**4404 个语义分块**，存储于 `D:/chroma_db`
- **测试集**：30 条人工标注 + 6 条压力测试用例（`data/test_set.json`）

### 如何新增药物知识（四步）

```bash
# 1. 在 data/texts/ 新建 <药品名>.txt，内容按【章节】切分（推荐：适应症/用法用量/禁忌/注意事项/药物相互作用/特殊人群用药）
# 2. 三重验证：章节骨架完整 / 文本质量 / 跨源互证（--new 严格校验；全库模式仅扫描不判失败）
python scripts/verify_knowledge.py --new 药品名
# 3. 构建索引（会全量重建；需在真实终端运行，且先停掉 Gradio 服务避免占用 D:/chroma_db）
python scripts/build_index.py
# 4. 重启服务
python run.py
```

> 全库体检：`python scripts/verify_knowledge.py`（不指定 --new 时对 `data/texts/` 全量扫描，输出质检报告到 `outputs/knowledge_report.json`）。

**说明书文本格式**（章节名可任意，检索与溯源均按【章节】切分）：

```text
【适应症】用于缓解轻至中度疼痛...
【用法用量】成人一次1片，一日3次...
【禁忌】对本品过敏者禁用...
【药物相互作用】...
```

### 从 PDF 导入（OCR 流程）

扫描版 PDF（无文本层）先 OCR 再进知识库：

```bash
# 1. 逐本 OCR：<name> 用 ASCII，输出到 data/ocr_raw/<name>.txt
python scripts/ocr_extract.py <name> <pdf路径>
# 2. 解析为知识库 txt（处方集按药 / 指南按病，处方集同时提取相互作用并入 CSV）
python scripts/parse_ocr.py
# 3. 重建索引 + 重启
python scripts/build_index.py
python run.py
```

### 检索策略：来源轮转均衡

- **无优先级**：候选按来源（药品/章节/本草纲目）分组，各来源轮流取 1 条，直到凑满 `TOP_K`（默认 12）条——任何一本书都不垄断结果
- **口语扩展**：口语症状词自动转医学术语（发烧→发热、拉肚子→腹泻、头疼→头痛等），保证现代文献能被召回
- **章节感知查询扩展**：问题意图自动映射到目标章节（如"怎么吃"→追加「用法用量」、"孕妇能吃吗"→追加「特殊人群用药」），提升目标章节命中率
- **病症荐药**：问"咳嗽用什么药"→ 跨说明书/处方集/指南/本草纲目综合给出全部治疗方案

## 🔌 API 示例

```bash
# 流式（SSE）
curl -N -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"布洛芬和阿司匹林能一起吃吗？","stream":true}'

# 非流式 JSON
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"孕妇能喝藿香正气水吗？","stream":false}'

# 反馈记录
curl -X POST http://127.0.0.1:8000/api/feedback \
  -H "Content-Type: application/json" \
  -d '{"question":"布洛芬和阿司匹林能一起吃吗？","answer":"...","rating":1}'
```

## ⚠️ 项目边界

- ❌ 不提供疾病诊断、不制定个性化用药方案、不联网搜索
- ❌ 不设用户注册登录、不支持语音/多模态
- ✅ 覆盖 590 份知识文本（处方集/指南/说明书/本草纲目）+ 941 对药物相互作用
- 每条回答仅供学习参考，**不构成医疗建议**；急症请立即拨打 120

## 🔍 在线 / 离线模式

- 配置 `LLM_API_KEY`（智谱 GLM-4-Flash 等 OpenAI 兼容接口）→ **在线模式**：RAG 路径直接流式生成，相互作用走 `create_react_agent` ReAct Agent 调用国内大模型。
- 未配置 Key → **离线模式**：确定性模板回答（完全可复现、零成本），用于演示与评测，全链路（检索→引用→护栏→免责声明）不变。
