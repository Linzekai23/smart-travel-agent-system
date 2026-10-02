"""test_mcp_server.py —— MCP Server 工具契约（内存 Client 直连，不启 stdio 进程）"""
import asyncio
import json
from pathlib import Path

import pytest
from fastmcp import Client

import mcp_server
from app.rag import retriever
from app.rag.ingest import load_corpus
from app.rag.vector_store import VectorStore

from conftest import FakeEmbedder, fake_weather

FIXTURE = Path(__file__).parent / "fixtures" / "sample_pois.jsonl"


@pytest.fixture()
def store(tmp_path):
    s = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    s.upsert_pois(load_corpus(FIXTURE))
    retriever.set_store(s)
    yield s
    retriever.set_store(None)


def _call(tool: str, arguments: dict):
    """内存 Client 调工具，返回 JSON 反序列化结果（工具返回 str，data/content 二选一）。"""
    async def _run():
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool(tool, arguments)

    result = asyncio.run(_run())
    raw = result.data if result.data is not None else result.content[0].text
    return json.loads(raw)


def test_list_tools():
    async def _run():
        async with Client(mcp_server.mcp) as client:
            return await client.list_tools()

    tools = asyncio.run(_run())
    assert {t.name for t in tools} == {"search_attractions", "get_weather"}


def test_search_attractions(store):
    payload = _call("search_attractions", {"query": "老街", "city": "成都"})
    assert payload and payload[0]["name"] == "宽窄巷子"
    assert {"name", "province", "city", "category", "rating", "lat", "lng",
            "description"} <= set(payload[0])


def test_search_attractions_city_suffix(store):
    """'成都市'（带后缀）与 '成都' 等价。"""
    payload = _call("search_attractions", {"query": "老街", "city": "成都市"})
    assert payload and payload[0]["name"] == "宽窄巷子"


def test_search_attractions_out_of_kb_city_falls_back_to_province(store):
    """库外城市（佛山）→ 放宽到所在省（广东）。"""
    payload = _call("search_attractions", {"query": "景点", "city": "佛山"})
    assert payload and {p["province"] for p in payload} == {"广东"}


def test_search_attractions_model_missing(monkeypatch, tmp_path):
    """模型未就绪 → 结构化错误（不让异常穿透协议层）。"""
    monkeypatch.setattr(retriever, "_store", None)
    monkeypatch.setattr("app.rag.download_model.default_model_dir",
                        lambda: tmp_path / "no-model")
    payload = _call("search_attractions", {"query": "随便"})
    assert "模型未就绪" in payload["error"]


def test_get_weather(store, monkeypatch):
    monkeypatch.setattr(mcp_server, "_weather_api", fake_weather)
    payload = _call("get_weather", {"city": "成都"})
    assert len(payload) == 3
    assert payload[0]["source"] == "open-meteo"


def test_get_weather_out_of_kb_city_falls_back_to_province(store, monkeypatch):
    monkeypatch.setattr(mcp_server, "_weather_api", fake_weather)
    payload = _call("get_weather", {"city": "佛山"})
    assert payload and "error" not in payload


def test_get_weather_unknown_city(store):
    payload = _call("get_weather", {"city": "巴黎"})
    assert "error" in payload
