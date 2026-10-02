# MCP Server（景点检索 + 天气）

把旅行助手的 RAG 景点检索与天气查询封装为独立 **MCP Server**（fastmcp，stdio 协议），
任意 MCP 客户端（Claude Desktop / Cursor / MCP Inspector 等）可直接调用知识库工具，
支持多工具编排（检索景点坐标 → 查天气）。

**选型说明**：主链路（LangGraph 5 Agent）保持原生工具调用——单应用内 MCP 引入的
序列化/协议开销没有收益；MCP 的价值在**工具跨应用复用与生态互通**，故以独立 server
形式提供并验证。

## 工具

| 工具 | 说明 |
|---|---|
| `search_attractions` | 语义检索全国景点知识库（BGE + 自建向量库，RRF 混合排序），可选 `city`/`province` 过滤；库外城市自动放宽到所在省 |
| `get_weather` | 城市未来 N 天逐日天气（Open-Meteo，免 key）；坐标取自景点知识库（该市无景点时放宽到所在省）；接口失败降级为模拟数据（`source: "simulated"`） |

两个工具都不需要 API key。

## 运行

```bash
cd backend
.venv/Scripts/python -m mcp_server      # stdio 传输（MCP 客户端以子进程方式启动它）
```

> 依赖已加入 `pyproject.toml`（`fastmcp>=3`）。本机 venv 的 `Scripts/pip.exe`
> 启动器因历史迁移失效（静默失败），一律用 `.venv/Scripts/python -m pip`。

## 接入 Claude Desktop

编辑 `%APPDATA%\Claude\claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "travel-assistant": {
      "command": "d:\\智能旅行系统\\backend\\.venv\\Scripts\\python.exe",
      "args": ["d:\\智能旅行系统\\backend\\mcp_server.py"],
      "cwd": "d:\\智能旅行系统\\backend"
    }
  }
}
```

要点：

- Windows 下 `command`/`args` 用**绝对路径**（`python` 可能不在客户端 PATH 里）；
- `args` 用 mcp_server.py 全路径后，即使 `cwd` 被忽略，脚本目录也会进入 `sys.path`，`import app` 依旧成立（双保险）；
- 改完在托盘**完全退出** Claude Desktop 再重启（关窗口不够）。

演示问句：

> 帮我查成都适合带老人慢慢逛的景点，再告诉我后天天气怎么样

模型会先后调用 `search_attractions` → `get_weather` 两个工具（多工具编排演示）。

## 冒烟验证（不装客户端也能验）

```bash
cd backend
{ printf '%s\n' \
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' \
 '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
 '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'; sleep 5; } \
 | .venv/Scripts/python -m mcp_server
```

预期：`id=2` 返回含 `search_attractions` / `get_weather` 的 tools 数组。

把 `tools/list` 换成 `tools/call` 可验真实调用（如
`{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_attractions","arguments":{"query":"适合带老人慢慢逛的景点","city":"成都"}}}`）——
此时首次调用要加载 BGE 模型，**stdin 需保持打开几十秒**（如把 `sleep 5` 改成 `sleep 40`），
提前 EOF 会让 server 在冷启动完成前退出、看不到响应。

可视化调试（需 Node）：`cd backend && npx @modelcontextprotocol/inspector .venv/Scripts/python.exe mcp_server.py`
——浏览器 UI 中直接列工具、填参数调用、看原始消息。

## 排障

| 现象 | 原因 / 处理 |
|---|---|
| 首次工具调用慢（数秒） | 正常：首次调用同步加载 BGE 模型（约 95MB，CPU） |
| 返回 `{"error": "BGE 模型未就绪：…"}` | 先运行 `python -m app.rag.download_model` |
| 返回 `{"error": "知识库中没有 xx 的坐标，无法查天气"}` | 该城市不在语料（34 省 1000+ 景点）内，属预期结构化错误 |
| 手工 printf 测试无响应 | 工具调用期间 stdin 不能提前 EOF（见上"冒烟验证"） |
| venv 相关怪现象 | 本 venv 由 `D:\agent` 迁移而来：`Scripts/activate` 与 `Scripts/pip.exe` 已失效，用全路径 `python.exe` / `python -m pip` |

## 测试

```bash
cd backend && .venv/Scripts/python -m pytest tests/test_mcp_server.py -q
```

8 个用例：内存 Client 直连（不启 stdio 进程）、FakeEmbedder 注入检索、天气 mock——
覆盖工具注册、JSON 返回、市名后缀归一、库外城市放宽到省、模型缺失与未知城市的结构化错误。
