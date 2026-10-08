# 后端服务镜像：FastAPI + LangGraph 多 Agent + BGE 本地向量检索
FROM python:3.12-slim

WORKDIR /app/backend
ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# torch 必须装 CPU 版（官方 CPU wheel 源）：
# Linux 上直接 pip install torch 会附带 CUDA 运行时 + 数 GB 的 nvidia-* 依赖，本项目只做 CPU 推理
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch --index-url https://download.pytorch.org/whl/cpu

# 先拷贝依赖清单与应用包再装依赖：改其他源码不会触发重装（torch 已装好，不会被重复拉取）
COPY pyproject.toml ./
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install . --index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 其余源码：mcp_server.py / scripts/ / tests/ 等
COPY . .

EXPOSE 8000
# 必须单进程运行：SSE 事件总线在进程内（app/events.py），多 worker 会丢跨进程事件
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
