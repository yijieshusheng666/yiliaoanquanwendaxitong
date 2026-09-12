# 企业级 RAG 改造路线图

> 面向秋招简历与面试深挖。评估基线：企业级 RAG 系统的通行标准（检索质量链路 / 真实链路评测 / 服务工程 / 可观测性 / 安全合规 / 数据治理 / 部署运维 / 编排可控性）。
> 评估时间：2026-09-11　评估对象：`医疗安全问答系统`（约 7400 行 Python）

---

## 一、定位结论

**当前定位：高完成度的个人 RAG 项目（准企业级），尚不构成企业级 RAG 项目。**

判断依据不在于功能数量，而在于企业级 RAG 的评判重心在另外三层：

| 层次 | 企业级关注点 | 本项目状态 |
|---|---|---|
| 检索质量链路 | 混合检索 + 重排 + 查询改写，可量化的召回/排序指标 | 单路向量召回 + 规则扩展，**无重排** |
| 评测可信度 | 评测跑在真实生成链路上，指标可被追问 | 评测跑在离线模板上，忠实度是字符串包含 |
| 服务工程 | 异步非阻塞、限流、缓存、降级、可观测 | 无缓存、无限流、同步推理阻塞事件循环 |

**一句话版**：你现在是"功能齐全"，企业级要求的是"质量可控 + 故障可控 + 成本可控"。

---

## 二、成熟度对照（8 维度，满分 5）

| # | 维度 | 现状 | 企业级 | 关键缺口 |
|---|---|---|---|---|
| 1 | 检索策略 | 2 | 5 | 无 Rerank、无 BM25 混合、无多路召回 |
| 2 | 评测体系 | 2 | 5 | 评测对象是离线模板而非真实 LLM 链路；无 Ragas 类指标 |
| 3 | 服务工程 | 2 | 5 | 无缓存/限流/降级；同步 CPU 推理阻塞 async 事件循环 |
| 4 | 可观测性 | 1 | 5 | 无 Trace、无指标埋点、无 token 成本统计 |
| 5 | 安全与合规 | 3 | 5 | CORS 全开、token 存 localStorage、无 PII 脱敏、无审计 |
| 6 | 索引与数据治理 | 4 | 5 | 缺增量更新；无删除/失效文档机制 |
| 7 | Agent 编排 | 3 | 5 | 文本解析式 ReAct，非 function calling / 状态机 |
| 8 | 部署与 CI | 1 | 5 | 无 CI、无镜像分层优化、无环境隔离 |

---

## 三、已经能打的亮点（现在就能写进简历）

这五点是你相对其他校招 RAG 项目的真实优势，**不要弱化**：

1. **版本化索引治理 + 原子切换 + 失败回滚**
   `app/core/index_versioning.py:95-103` 临时文件 + `os.replace` 原子写 MANIFEST；
   `app/core/retrieval.py:120-144` 新版本目录构建失败只清理临时目录，已生效版本不受影响。
   → 面试话术："索引重建是可回滚的，构建失败不会让线上检索降级。"

2. **语料指纹驱动的重建判定（含配置指纹）**
   `index_versioning.py:58-78` 指纹覆盖 `data/texts/*.txt` + `interactions.csv` 的逐文件 sha256，
   并纳入嵌入模型标识名 / 分块上限 / 集合名（`fingerprint_config()`，:39-55）。
   → 这是很多企业项目都没做到的点：换模型不重建索引是个隐蔽的严重 bug。

3. **空语料拒绝构建（防御性设计）**
   `retrieval.py:104-109` 语料为空直接 `raise RuntimeError`，不注册空版本。
   注释里写清了原因：指纹一旦与空语料绑定，之后永远判定"未变化"，服务会永久答"未找到"。
   → 面试话术："这是一个'一旦发生就几乎不可诊断'的故障，所以我选择让服务启动失败。"

4. **可复现的离线确定性回答器**
   `app/core/offline.py` + `service.py:282-291` 的 `online` 开关，
   让评测不依赖 LLM 波动，指标可复现、零成本。
   → 这是正确的工程直觉，但**需要升级**（见 P0-2）。

5. **双层安全护栏 + 否定语境豁免**
   `app/core/guardrails.py:36-40` 规则拦截（急症 100% 拦截，不经过模型）；
   `:51-64` 否定语境豁免 + 疑问歧义排除，把误报率压到 0%。
   → 面试话术："安全兜底不走模型，因为模型本身可能被绕过；同时用否定豁免控制误报，
   否则'这不是心梗'也会被拦，用户体验直接崩。"

---

## 四、P0 改造（决定"能不能称企业级"）

### P0-1　检索层引入 Rerank（最高优先级）

**问题**：`retrieval.py:229` 只有一路 `self.db.similarity_search()`，
`_diversify()`（:151-168）做的只是**按药品名轮转抽样**，属于"来源均衡"而非"相关性排序"。
`TOP_K=12`（`config.py:47`）意味着 12 条候选直接进 prompt，噪声比例高。

**改法**：
1. 两阶段检索：粗排 `fetch_k = 50` → 精排 Top-8。
2. 加 `bge-reranker-base`（或 `bge-reranker-v2-m3`）做 cross-encoder 重排。
   新增 `app/core/reranker.py`，接口 `rerank(query, docs, top_n)`。
3. 保留 `_diversify()` 但**移到 rerank 之后**，作为多样性后处理——这样才是"相关性优先 + 来源均衡"的正确顺序。
4. 分块策略升级：当前 `CHUNK_MAX_CHARS=500` 固定切分（`config.py:49`），
   改为按章节语义切分 + 相邻块 overlap 50~80 字，避免跨块语义断裂。

**验收**：`section_hit` 从 0.7857 提到 ≥ 0.90（这是你现有报告里最弱的一项）；
新增 `MRR@10` / `NDCG@10` 指标。

**简历话术**：
> 针对向量召回噪声问题，实现"粗排 50 → BGE-Reranker 精排 8"两阶段检索，
> 章节命中率从 78.6% 提升至 XX%，并保留来源轮转策略做多样性后处理。

---

### P0-2　评测体系换成真实链路 + LLM-as-Judge

**问题（这条最容易被面试官击穿）**：
`scripts/evaluate.py:92` 的 `answer_once(q, None, online=(args.mode == "online"))`
默认 `mode="no-llm"`，也就是说**报告里的指标全是离线模板拼装的成绩，不是真实 RAG 链路的成绩**。
更关键的是 `evaluate.py:100`：

```python
faithful = item.get("answer_key", "") in answer
```

"忠实度 0.9286" 的真实含义是"92.86% 的回答里恰好包含了预设关键字"——
这是**字符串包含**，不是忠实度。面试官只要问一句"你这个 faithfulness 怎么算的"，就会露馅。

**改法**：
1. 双轨评测：`--mode no-llm` 保留（回归基线，快、免费），
   新增 `--mode online` 作为**发布门禁**（真实链路，指标才写进简历）。
2. 引入 **Ragas** 四指标：`faithfulness` / `answer_relevancy` / `context_precision` / `context_recall`。
3. 在 CI 里加**指标回归阈值**：任一核心指标环比下降超过 3% 则判定失败。
   `outputs/` 里已经有 `eval_report_baseline_*.json` / `eval_regression_*.json` 的习惯，把它固化成脚本。
4. 评测集扩容：36 条 → 100+ 条，并补充**对抗样本**
   （prompt 注入、诱导编造、超纲药名、多药交叉），单列 `adversarial` 类型。

**简历话术**：
> 构建双轨评测体系：离线确定性基线（可复现、零成本）+ 在线 Ragas 四指标门禁；
> 覆盖 100+ 标注样本与 20+ 对抗样本，核心指标接入 CI 做回归卡点。

---

### P0-3　修掉事件循环阻塞（技术硬伤，讲出来很加分）

**问题**：`service.py:302-304`

```python
kb = get_knowledge_base()
is_interaction, drugs = classify_interaction(question, history)
docs = kb.search(question, k=TOP_K)
```

这三行在 `async def answer_stream()` 内部，但 `kb.search()` 底层是
`sentence-transformers` 的 **CPU 同步推理**。它会**阻塞整个 FastAPI 事件循环**——
一个用户提问时，其他所有 SSE 连接全部卡住。

**改法**：
```python
docs = await asyncio.to_thread(kb.search, question, TOP_K)
```
同理处理 `_tool_retrieve()`（`service.py:175-176`）和 reranker 调用。
进阶：把嵌入/重排改成独立推理服务（或 ONNX Runtime + 批处理队列），彻底解耦。

**简历话术**：
> 排查出 CPU 嵌入推理阻塞 asyncio 事件循环的并发瓶颈，
> 通过 `asyncio.to_thread` 卸载阻塞调用，并发 QPS 从 X 提升至 Y。

> ⚠️ 这条务必自己动手做完并能讲清原理，它是面试官区分"真懂异步"和"只会写 async 关键字"的分水岭。

---

### P0-4　引用不能靠模型自觉（幻觉防线）

**问题**：`RAG_TEMPLATE`（`service.py:37-55`）要求模型"每个关键结论后必须标注 `[n]`"，
但**没有任何事后校验**。当前 `citation_accuracy = 1.0` 是在离线模板下算出来的
（模板是人写的，编号当然对），在线模式下模型完全可能标错或不标。

**改法**：
1. 生成后校验：解析回答里的 `[n]` → 检查 `n` 是否越界 → 检查该来源与结论的语义支撑度。
2. 越界引用直接剥离该引用标记并记录告警。
3. 新增指标 `citation_grounding_rate`：引用编号与来源内容真实对应的比例。

**简历话术**：
> 实现引用后置校验（越界检测 + 语义支撑度打分），
> 将模型自标注引用的可信率从 XX% 收敛到 XX%。

---

### P0-5　基础安全加固（改动量小，收益立竿见影）

| 问题 | 位置 | 改法 |
|---|---|---|
| CORS 全开 `allow_origins=["*"]` | `server.py:71-76` | 改为白名单，从环境变量读 |
| token 存 localStorage（XSS 可窃取） | `gradio_app.py` 前端 | 改 HttpOnly + Secure + SameSite Cookie，配 CSRF token |
| 无登录限流（可暴力破解） | `user_routes.py:64-78` | 加 IP/账号维度滑动窗口限流 + 失败锁定 |
| 无 LLM 调用限流（成本失控） | `server.py:151` | 按 user_id 配额 + 全局并发信号量 |
| 无 PII 脱敏 | 全链路 | 提问入口做手机号/身份证/姓名脱敏后再落库 |

> 注意：`_LOCK = threading.Lock()`（`auth.py:26`、`chat_history.py:19`）是**进程内锁**，
> 多 worker 部署时完全失效，且 SQLite 会成为写瓶颈。见 P2-4。

---

## 五、P1 改造（决定"像不像企业级"）

### P1-1　混合检索 + RRF 融合
`retrieval.py` 目前是纯向量。加 BM25（`rank_bm25` 或 Elasticsearch），
用 **RRF（Reciprocal Rank Fusion）** 融合两路结果。
药品名、化学名这类**精确匹配场景**，BM25 显著强于向量。
→ 配合 P0-1 形成完整链路：`BM25 + Vector → RRF → Rerank → Diversity → Top-K`。

### P1-2　语义缓存
高频问题（如"布洛芬怎么吃"）重复检索 + 重复调 LLM 是纯浪费。
加两级缓存：**精确命中缓存**（问题哈希 → 回答）+ **语义缓存**（嵌入相似度 > 0.95 命中）。
生产用 Redis；演示可用 `functools.lru_cache` + sqlite。
→ 简历可写"降低 LLM 调用量 XX%、P95 延迟从 X ms 降至 Y ms"。

### P1-3　可观测性（当前 1/5，补齐最快）
1. **全链路 Trace**：LangSmith 或 OpenTelemetry，记录
   `检索耗时 / 召回条数 / rerank 分数 / prompt token / completion token / 总耗时`。
2. **指标暴露**：`/metrics` 接 Prometheus——QPS、P95、缓存命中率、护栏命中率、LLM 失败率。
3. **成本统计**：按 user_id / 会话累计 token 与费用，落 SQLite，出个日报。
→ 简历话术："建立全链路可观测体系，单次问答平均 token 成本可归因到用户与模块。"

### P1-4　增量索引
当前新增一份说明书要走**全量重建**（`build_index.py`）。
改法：Chroma 支持 `add_documents` / `delete(where={"drug": ...})`，
按 `doc_id` 做 upsert + 删除，配合 MANIFEST 记录 `doc_id → 版本` 映射。
→ 简历话术："索引更新从全量重建降级为秒级增量 upsert，重建耗时从 X 分钟降至 Y 秒。"

### P1-5　LLM 降级链路
`service.py:324-328` 出错时直接返回"抱歉，生成回答时发生错误"。
企业级要求**多级降级**：主模型失败 → 备用模型（如 qwen）→ 离线确定性回答器
（`offline.py` 已经写好了，直接复用）。加超时 + 指数退避重试。

---

## 六、P2 改造（决定"好不好讲透"）

### P2-1　Agent 改用 function calling / LangGraph
`service.py:238-241` 用的是 `create_react_agent` + `handle_parsing_errors=True`，
本质是**让模型输出规定格式的文本再正则解析**，`max_iterations=4` 说明它在防死循环。
"需要容错解析"本身就是这个范式的固有缺陷。
→ 改用原生 tool calling，或用 LangGraph 显式建状态机
（`classify → retrieve → rerank → tool_call → generate → validate`），
状态、重试、人工介入点全部可控。

### P2-2　PII 脱敏与医疗合规
医疗场景必须做：提问入口脱敏、日志脱敏（`logging_setup.py` 目前原样落盘 `question[:100]`）、
审计日志（谁在什么时候问了什么、系统怎么答的、是否触发护栏）、数据保留策略。

### P2-3　CI/CD
无 `.github/workflows`。加一条基础流水线：
`ruff 静态检查 → pytest（7 个测试文件）→ 索引构建 → 离线评测门禁 → 镜像构建`。
→ 这是"企业级"最廉价的可信度证明，半天就能做完。

### P2-4　存储与向量库解耦
- SQLite → PostgreSQL（业务数据），向量库 → pgvector 或 Milvus/Qdrant。
- `retrieval.py` 直接 `import Chroma`，无抽象层。抽出 `VectorStore` 接口，
  实现可插拔（Chroma / pgvector / Qdrant），换库不改上层。
- 引入 Alembic 做迁移管理（现在 `chat_history.py:64-89` 是手写迁移）。

---

## 七、执行优先级建议

| 顺序 | 任务 | 工作量 | 面试收益 |
|---|---|---|---|
| 1 | P0-2 评测换真实链路 + Ragas | 中 | ★★★★★（拆掉最大的雷） |
| 2 | P0-1 Rerank 两阶段检索 | 中 | ★★★★★（RAG 核心考点） |
| 3 | P0-4 引用后置校验 | 小 | ★★★★ |
| 4 | P2-3 CI 流水线 | 小 | ★★★★（性价比最高） |
| 5 | P0-3 异步阻塞修复 | 小 | ★★★★ |
| 6 | P1-2 语义缓存 | 小 | ★★★ |
| 7 | P1-3 可观测性 | 中 | ★★★★ |
| 8 | P0-5 安全加固 | 小 | ★★★ |
| 9 | P1-1 混合检索 RRF | 中 | ★★★★ |
| 10 | P2-1 LangGraph 重写 | 大 | ★★★ |

> 建议前 4 项做完再更新简历——这 4 项能让你从"做过 RAG"变成"能把 RAG 做对"。

---

## 八、面试追问预案

准备好被问这几个，每一个都要能讲出手上的真实数字：

| 可能的追问 | 你的回答要点 |
|---|---|
| "你的 faithfulness 怎么算的？" | 必须回答 Ragas 的 LLM-as-judge + 具体 judge prompt 设计，**绝不能是字符串包含** |
| "检索为什么用向量不用 BM25？" | 答"两者都用，RRF 融合"，并说明药品名精确匹配场景 BM25 更强 |
| "为什么需要 Rerank？" | 答双塔嵌入是"查询和文档各自编码、只算余弦"，交互不充分；cross-encoder 是"拼接后联合编码"，精度高但慢，所以只能用在精排小候选集 |
| "12 条上下文不会超长吗？" | 答 token 预算管理：动态 Top-K + 上下文压缩 + 按 token 截断 |
| "并发上来了怎么办？" | 答事件循环阻塞修复 + 缓存 + 限流 + 嵌入推理服务化 |
| "怎么保证不胡说？" | 答三层：提示词约束 → 引用后置校验 → 护栏兜底；并承认 LLM 链路仍有幻觉残余风险，所以医疗场景必须人工复核 |
| "索引更新要多久？" | 答指纹判定跳过无谓重建 + 增量 upsert 后的真实耗时 |

---

## 九、一句话总结

**你的项目在"数据治理"和"安全兜底"上已经是企业级思路，
在"检索质量"和"评测可信度"上还是个人项目水平。
补齐 P0 的四项，这个项目就可以在简历上写"企业级 RAG 架构"了。**
