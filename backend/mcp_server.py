"""MCP Server：把旅行助手的两类能力暴露给任意 MCP 客户端（stdio 协议）。

工具：
- search_attractions  语义检索景点知识库（BGE + 自建向量库，RRF 混合排序）
- get_weather         城市天气（Open-Meteo 真实 API，失败降级模拟）

运行：cd backend && python -m mcp_server    （stdio 传输；Claude Desktop 配置见 docs/mcp.md）
选型说明：主链路（LangGraph）保持原生工具调用，本 server 用于工具跨应用复用与生态互通。
"""
from __future__ import annotations

import json

from fastmcp import FastMCP

from app.rag.retriever import RRF_K, RRF_WEIGHT, get_store, normalize_region
from app.tools.weather_api import get_weather as _weather_api

mcp = FastMCP("travel-assistant-tools")


def _normalize_region(name: str) -> tuple[str | None, str | None]:
    """省/市名归一；兼容"成都市/四川省"这类带后缀写法（retriever 只认原名/别名/拼音）。"""
    if not name:
        return None, None
    province, city = normalize_region(name)
    if province is None and name.endswith(("市", "省")):
        province, city = normalize_region(name[:-1])
    return province, city


def _err(msg: str) -> str:
    return json.dumps({"error": msg}, ensure_ascii=False)


@mcp.tool()
def search_attractions(query: str, city: str = "", province: str = "", k: int = 5) -> str:
    """语义检索全国景点知识库（34 省级行政区 1000+ 景点）。

    query 为自然语言描述，如"适合带老人慢慢逛的景点"；city/province 可选（如"成都"/"四川"），
    用于缩小范围。返回 JSON 数组，每条含 name/province/city/category/rating/price_tier/
    lat/lng/description/tags（无相关性分数）。该市无结果时自动放宽到所在省；无结果返回 []。
    """
    p_city, c_city = _normalize_region(city)
    p_prov, _ = _normalize_region(province)
    c_final = c_city or (city or None)      # 归一失败就用原样过滤（查不到自然返回空）
    p_final = p_city or p_prov or (province or None)
    try:
        results = get_store().query(query, city=c_final, province=p_final, k=k,
                                    rrf_weight=RRF_WEIGHT, rrf_k=RRF_K)
        if not results and c_final and p_final:
            # 库外城市（如"佛山"）：放宽到所在省，与主链路三级 fallback 语义一致
            results = get_store().query(query, province=p_final, k=k,
                                        rrf_weight=RRF_WEIGHT, rrf_k=RRF_K)
    except RuntimeError as e:              # BGE 模型 / 向量库未就绪
        return _err(str(e))
    return json.dumps(results, ensure_ascii=False, indent=1)


@mcp.tool()
def get_weather(city: str, days: int = 3) -> str:
    """查询城市未来 days 天逐日天气（字段：date/t_max/t_min/condition）。

    city 为城市名（如"成都"）；坐标取自景点知识库（该市无景点时放宽到所在省）。
    source 字段："open-meteo" = 真实数据，"simulated" = 接口失败时的模拟降级。
    知识库无该城市坐标时返回 {"error": ...}。
    """
    p, c = _normalize_region(city)
    try:
        store = get_store()
        hits = store.query("", city=c, k=1) if c else []   # 空 text → 该市评分最高的 POI
        if not hits and p:
            hits = store.query("", province=p, k=1)
    except RuntimeError as e:
        return _err(str(e))
    poi = hits[0] if hits else None
    if poi is None or poi.get("lat") is None:
        return _err(f"知识库中没有 {city} 的坐标，无法查天气")
    weather = _weather_api(float(poi["lat"]), float(poi["lng"]), days=days)
    return json.dumps(weather, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    mcp.run(transport="stdio")
