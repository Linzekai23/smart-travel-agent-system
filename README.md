# 智能旅行系统（智能旅行助手为主功能）

智能旅行助手（多 Agent）+ 系统外壳的 Web 应用 —— 作品集项目。
打开即系统主页（首页导航式），**智能旅行助手是主要功能**：用户以自然语言提出出行需求
（**支持全国 34 个省级行政区的著名景点检索**），多个专业 Agent 协作完成行程规划、天气查询、
预算分配与个性化推荐，并接入**高德真实景点/餐厅/酒店数据**（地址、照片、地图打点）。
另有四个辅助功能页：我的行程、交通规划、攻略浏览、出行清单。

架构：**LangGraph supervisor 模式 + 5 个 Agent**（Analyst / Researcher / Budget / Planner / Supervisor），
FastAPI 后端 + React 前端，SSE 实时推送协作过程。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · LangGraph（含 langgraph-checkpoint-sqlite 会话持久化） · SQLite · httpx · Pillow（酒店照片择优评分） |
| LLM | DeepSeek（OpenAI 兼容，JSON 模式） |
| **RAG 知识库** | **BGE（bge-small-zh-v1.5，ModelScope 下载）+ 自建 numpy 向量库**，全国 34 省级行政区 1000+ 著名景点（省份-城市-景点三级粒度检索） |
| **MCP** | fastmcp（stdio）—— 景点检索/天气已封装为 MCP Server，Claude Desktop 可直接调用（[docs/mcp.md](docs/mcp.md)） |
| 前端 | React 19 · Vite · TypeScript · Tailwind v4 · **Ant Design v5** · Leaflet / react-leaflet |
| 实时通信 | SSE（ping / agent_status / itinerary_update 事件） |
| 部署 | Docker Compose（Nginx 反代 + 多阶段构建 · torch CPU 版） |

## 目录结构

```
backend/   FastAPI + LangGraph（agents/ 5 个 Agent · rag/ 向量知识库 · tools/ 天气 · llm/ Provider · api/ 含 trips/route/guide）+ mcp_server.py（MCP Server）
frontend/  React 首页导航式（App.tsx 按 view 切换：助手 + 我的行程/交通规划/攻略浏览/出行清单；components/ 含地图/图片/工作流组件）
docs/      架构文档与各里程碑设计文档
scripts/   一键启动脚本（bash scripts/dev.sh）
部署       docker-compose.yml · backend/Dockerfile · frontend/Dockerfile（Docker 一键部署）
```

## 功能清单

**系统外壳**
- **首页导航式**：系统主页功能卡片入口，智能旅行助手为 C 位主功能；顶部栏全局导航（助手/我的行程/交通规划/攻略浏览/出行清单），切页不丢助手会话
- **我的行程**：助手行程一键「保存到我的行程」（快照库）；列表卡片（天数/更新时间）+ 详情查看（复用行程面板）+ 删除
- **交通规划**：起终点（城市 + 地点名，高德地理编码）→ 公交/驾车/步行方式，实时查询耗时/距离/费用，**结果附高德地图**（起终点标记 + 完整路线线，公交/地铁画出线路走向）；无 key 或失败自动降级为直线距离估算并标注"仅供参考"（地图画虚线直线）
- **攻略浏览**：按城市浏览景点/美食/住宿三 Tab（景点/美食/住宿优先高德真实 POI，无高德数据时景点回退知识库语料）
- **出行清单**：证件/衣物/数码/药品/其他分类勾选 + 自定义添加，状态自动保存本机浏览器（localStorage）

**助手（主功能，核心零改动）**
- **多 Agent 协作规划**：Analyst（需求分析）→ Researcher‖Budget（区域检索 + 预算分配，并行）→ Planner（行程规划）→ Supervisor（汇总建议）；发送期间对话框下方实时展示各 Agent 工作进度（SSE）
- **自然语言行程**：目的地 / 天数 / 预算 / 偏好 → 逐日行程（时段建议、详细介绍、天气提示）；对话式修改重排（"第二天换成博物馆"）与刷新后会话恢复
- **全国 34 省景点检索**：RAG（BGE + 自建向量库，1000+ 景点）省份-城市-景点三级粒度；库外城市自动 fallback 到所在省；高德真实景点优先、RAG 兜底
- **高德真实景点/餐厅/酒店**：景点候选高德优先、RAG 语义检索兜底（无 key/失败/无结果时），景点介绍由 LLM 补写 150-250 字结构化内容（历史沿革/看点/游玩建议/交通）；地址/照片进行程与地图（三色打点：景点=品牌色、餐厅=橙、酒店=蓝）；酒店多张照片按"阳光指数"自动择优（太暗时兜底城市酒店大堂美图）；同一商家全程只出现一次；**无高德 key 时自动降级为示例数据**
- **地图交互**：Leaflet + 高德瓦片；按天筛选；**点击景点/餐厅/酒店条目 → 视口滚到地图 + 飞行定位 + 弹出详情气泡**
- **行程面板**：结构化日卡（Timeline）、预算分配表（说明含估算依据 + 占比列）、详细行程总结 + 警示 + tips（自动去重）
- **精简对话栏**：回复每条一行，详细介绍/预算/总结都在右侧面板；错误红色气泡提示

## 快速开始

### 一键启动（推荐）

```bash
bash scripts/dev.sh           # 依赖与 RAG 库就绪时直接启动（后端 + 前端 + 打开浏览器）
bash scripts/dev.sh --setup   # 首次运行：自动下载 BGE 模型、生成 34 省语料、向量入库后启动
```

> 需先配置 `DEEPSEEK_API_KEY` 环境变量；脚本会自动检查后端/前端依赖与 RAG 库是否就绪。
> 架构与协作设计（mermaid 图）见 [docs/architecture.md](docs/architecture.md)。

### 1. 后端

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"     # 含 numpy/transformers/torch 等 RAG 依赖
export DEEPSEEK_API_KEY=sk-xxx          # DeepSeek 平台申请；配置后聊天功能可用（Git Bash；cmd 用 set）
export AMAP_KEY=xxx                     # 高德开放平台 Web 服务 key，可选；缺失时餐厅/酒店为示例数据
# 首次运行需准备 RAG 知识库（三步）：
.venv/Scripts/python -m app.rag.download_model   # 1. 下载 BGE 模型（ModelScope，约 95MB）
.venv/Scripts/python -m app.rag.generate        # 2. 生成 34 省 POI 语料（DeepSeek 约 34 次调用；扩量可加 --rounds 3）
.venv/Scripts/python -m app.rag.ingest          # 3. 向量化入库（自建 numpy 向量库）
.venv/Scripts/uvicorn app.main:app --port 8000
```

### 2. 前端

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173（/api 代理到 :8000）
```

浏览器打开 http://localhost:5173，进入系统主页（助手为 C 位大卡，下方为我的行程/交通规划/攻略浏览/出行清单入口）。
点进**智能旅行助手**，输入"10月去成都玩3天，预算8000，喜欢美食"：
发送期间对话框下方实时点亮各 Agent 工作流程；行程生成后右侧展示地图、日卡、预算与总结。
点击任意景点/餐厅/酒店条目，地图自动飞行定位并弹出详情；按天 Tab 筛选地图打点。
输入"广东"会检索全省著名景点；库外城市（如"佛山"）fallback 到广东省其他景点。
继续发送"第二天换成博物馆"，助手保留上下文重排行程；刷新页面后历史对话自动恢复。
行程面板出现后点击「保存到我的行程」，可在顶部导航的**我的行程**中查看/删除（快照库，刷新不丢）。

> 语料为 **AI 生成示例数据，坐标仅供参考**；餐厅/酒店数据来自高德地图，营业信息可能变动。
> 如某城景点数据不理想，可编辑 `backend/data/poi_corpus.jsonl` 后重跑 `python -m app.rag.ingest` 增量入库。

## Docker 部署（推荐：一条命令跑起前后端）

前后端与反向代理已容器化：Nginx 托管前端静态文件，并把 `/api/` 反代到后端容器（同源，无跨域问题）。

```bash
cp backend/.env.example backend/.env   # 填入 DEEPSEEK_API_KEY（必需）与 AMAP_KEY（可选）
docker compose up -d --build
```

浏览器打开 **http://localhost:8080** 即为完整应用。端口冲突时用 `PORT=8888 docker compose up -d`。

- 后端 `backend/data/`（BGE 模型 / 向量库 / 语料 / SQLite，约 200MB，全部被 gitignore）以卷挂载进容器，容器与本机开发共享同一份数据。
- BGE 模型是**首次检索时懒加载**：第一次聊天 / 攻略请求多等 10~40 秒属正常，之后保持常驻（约 1GB 内存）。
- 常用命令：`docker compose logs -f backend`（后端日志）、`docker compose down`（停止）、`docker compose up -d --build`（重建）。

**迁移到云服务器**：服务器装好 Docker 后，上传仓库与 `backend/data/` 目录，执行 `docker compose up -d --build`，开放端口后访问 `http://服务器IP:8080` 即可。若数据不便上传，也可用容器重建 RAG 数据（`download_model` 走 ModelScope，国内可达）：

```bash
docker compose exec backend python -m app.rag.download_model
docker compose exec backend python -m app.rag.generate
docker compose exec backend python -m app.rag.ingest
```

## 测试

```bash
cd backend && .venv/Scripts/python -m pytest -q   # 247 tests 全部 mock（FakeProvider/FakeEmbedder），无需 API Key、无需模型、无网络
cd frontend && npm run build && npm run lint      # 前端门禁：tsc + vite 构建 + oxlint
```

## 检索评估（2026-09）

50 条人工标注查询（city 20 / semantic 15 / province 5 / alias 5 / edge 5），含**零假设基线**对照。

```bash
cd backend && python -m scripts.eval_retrieval   # 产出 eval_report.md
```

| 变体 | Hit@8 | Recall@8 | MRR |
|---|---|---|---|
| **`hybrid`（线上默认：区域过滤 + RRF 混合排序）** | **100.0%** | **70.5%** | **0.778** |
| `semantic`（改动前：纯 BGE 语义） | 97.9% | 61.8% | 0.767 |
| `rating`（零假设：不看查询，只按评分降序） | 97.9% | 70.3% | 0.739 |
| `keyword`（bigram 词法排序） | 93.8% | 69.9% | 0.671 |
| `nofilter`（全国语义检索，不过滤区域） | 66.7% | 37.9% | 0.524 |

**评估发现的真问题**（完整分析见 [docs/retrieval-eval.md](docs/retrieval-eval.md)）：

1. **纯语义检索并非全面领先**——整体 Hit@8 与"只按评分排序"打平，**Recall@8 反低 8.5pct**。
   分类型看：属性类查询（"适合带老人慢慢逛"）语义**赢 8.0pct**，
   但"著名景点/必去"类查询**输 35~44pct**。
2. **根因：语义向量里没有"知名度"信号**——`_doc_text()` 只拼文本、不含 `rating`，
   而"湖南有哪些著名景点"想要的恰是热度最高的。这是一个**真实的产品缺陷**：
   用户问"北京必去的景点"会拿到语义相似但不出名的景点。
3. **三级区域过滤是最大单项增益**：Hit@8 **66.7% → 97.9%**，属性类 Recall@8 **3.6% → 66.9%**。

**改进：RRF 混合排序（已落地）**

`VectorStore.query()` 支持 `rrf_weight`/`rrf_k`，按
`1/(K+语义排名) + w/(K+热度排名)` 融合（余弦与评分量纲不可比，RRF 只用排名、免归一化）。
参数用 `python -m scripts.eval_retrieval --sweep` 网格搜索确定，取 **w=0.75 / K=10**。

改后相对改动前：**5 个类别全部不退化**，Hit 97.9%→100.0%、Recall 61.8%→70.5%、MRR 0.767→0.778；
相对"只按评分排序"的零假设基线，**Recall 持平、MRR 更高、属性类高 11.1pct**，
但省/别名/边界三类仍低（正确解法应按查询类型动态调 w，已列入下一步）。

k 曲线：Hit@k 在 k=8 后饱和，但 **Recall@k 仍在涨**（70.5% → 80.9% @ k=10）——
k=8 的定位是"给 Planner 够用的候选"，不是"召回全部答案"。

> 诚实声明：50 条为单人标注、无双人一致性校验；语料为 AI 生成，评分分布与真实平台不同，
> **绝对值不可外推，变体间的相对比较才是本次实验的价值**。
> 参数网格搜索在 50 条上有过拟合风险，选 w=0.75 而非网格最优组，正是为了避开尖峰。

## MCP Server（2026-10）

景点语义检索与天气查询已封装为独立 MCP Server（fastmcp，stdio 协议），Claude Desktop 等 MCP 客户端可直接调用知识库工具，支持多工具编排（检索景点坐标 → 查天气）：

```bash
cd backend && .venv/Scripts/python -m mcp_server   # stdio 运行；客户端配置与冒烟验证见 docs/mcp.md
```

选型说明：主链路（LangGraph 5 Agent）保持原生工具调用——单应用内 MCP 引入的序列化/协议开销没有收益；MCP 化的价值在**工具跨应用复用与生态互通**，以独立 server 形式先打通验证。新增 8 个内存 Client 测试（[tests/test_mcp_server.py](backend/tests/test_mcp_server.py)）。

## 里程碑

| 阶段 | 状态 |
|---|---|
| M1 骨架（FastAPI + SSE + SQLite + 图 + 前端骨架） | ✅ 完成 |
| M2 最小闭环（DeepSeek + **RAG POI 知识库** + Analyst/Planner + 天气） | ✅ 完成 |
| M3 完整协作（34 省景点库 + Supervisor 路由 + Researcher/Budget + 并行） | ✅ 完成 |
| M4 对话能力（会话持久化 + 修改重排） | ✅ 完成 |
| M5 地图与交付（Leaflet 地图 + 结构化日卡 + 文档 + 演示脚本） | ✅ 完成 |
| 高德真实餐厅/酒店接入（POI 检索 + enrich + 照片择优 + 地图打点） | ✅ 完成 |
| UI 重设计（Ant Design 两栏布局 + 地图交互 + 对话栏 Agent 工作流） | ✅ 完成 |
| 智能旅行系统扩展（首页导航壳 + 我的行程 + 交通规划 + 攻略浏览 + 出行清单） | ✅ 完成 |

详细设计见 [docs/superpowers/specs/](docs/superpowers/specs/)（整体设计 / M4 对话 / M5 地图 / 高德真实商家接入）。
架构与系统扩展说明见 [docs/architecture.md](docs/architecture.md)。
