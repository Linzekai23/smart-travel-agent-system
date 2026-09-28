"""RAG 检索对外接口（Researcher 依赖注入点）。

- normalize_region：省/城市名（中文、别名、拼音）→ (省份简称, 城市名 | None)
- search_pois：三级粒度 fallback —— 库内城市→该市；库外城市→所在省；直接省名→全省
- search_nearby：同省候选 + haversine 距离排序（数据量小，全量计算）
- get_store：惰性单例（CHROMA_PERSIST_DIR + 真实 BGE）；set_store 供测试注入
"""
from __future__ import annotations

import math

from app.rag.generate import CITY_EN
from app.rag.province_cities import CITY_TO_PROVINCE, PROVINCE_ALIASES
from app.rag.vector_store import VectorStore

# 城市别名（中文 + 拼音，大小写不敏感）→ 城市名
# 中文键覆盖全省城市清单（含库外城市如"佛山"，供三级 fallback 经 CITY_TO_PROVINCE 转省）
_CITY_ALIASES: dict[str, str] = {c: c for c in CITY_TO_PROVINCE}
_CITY_ALIASES.update({en: c for c, en in CITY_EN.items()})

_store: VectorStore | None = None

# RRF 混合排序默认参数（网格搜索见 backend/eval_report.md）：
#   0 = 纯语义（改动前行为）；>0 = 语义排名 + 热度排名倒数融合。
# 依据 docs/retrieval-eval.md：纯语义在"著名景点/必去"类查询上系统性劣于评分排序，
# 而在"属性"类查询上更优；RRF 用来同时拿到两边的收益。
RRF_WEIGHT = 0.75
RRF_K = 10


def set_store(store: VectorStore | None) -> None:
    """测试注入点：替换全局检索存储（FakeEmbedder 版）。"""
    global _store
    _store = store


def get_store() -> VectorStore:
    """惰性单例；首次调用创建（CHROMA_PERSIST_DIR + 真实 BGE）。

    模型未下载时抛 RuntimeError 提示先执行 `python -m app.rag.download_model`——
    不在服务进程内触发联网下载（避免请求挂起），下载是显式 CLI 步骤。
    """
    global _store
    if _store is None:
        from app.rag.download_model import default_model_dir
        from app.rag.embeddings import Embedder
        from app.rag.ingest import default_chroma_dir

        model_path = default_model_dir()
        if not (model_path.exists() and any(model_path.iterdir())):
            raise RuntimeError(
                f"BGE 模型未就绪：{model_path}。请先运行 python -m app.rag.download_model"
            )
        embedder = Embedder(str(model_path))
        _store = VectorStore(str(default_chroma_dir()), embedder)
    return _store


def normalize_region(name: str) -> tuple[str | None, str | None]:
    """归一为 (省份简称, 城市名)；城市优先（先匹配城市别名，再匹配省别名）。

    返回示例：("广东", "广州") / ("广东", None) / (None, None)。
    """
    key = name.strip().lower()
    city = _CITY_ALIASES.get(key)
    if city is not None:
        return CITY_TO_PROVINCE[city], city
    province = PROVINCE_ALIASES.get(key)
    if province is not None:
        return province, None
    return None, None


def _resolve(name: str) -> tuple[str | None, str | None]:
    """三级 fallback 决策：城市在库返回 (province, city)；城市不在库返回 (province, None)（全省兜底）。"""
    province, city = normalize_region(name)
    if province is None:
        return None, None
    if city is None:
        return province, None
    if city in CITY_EN:  # 城市在语料中（有拼音即景点城市）
        return province, city
    return province, None  # 库外城市 → 所在省兜底


def search_pois(
    name: str,
    *,
    query: str | None = None,
    k: int = 8,
) -> list[dict]:
    """三级粒度检索：库内城市→该市；库外城市/直接省名→全省。

    排序用 RRF 混合（语义 + 热度），参数见 RRF_WEIGHT / RRF_K。
    """
    province, city = _resolve(name)
    if province is None:
        return []
    return get_store().query(query or "", city=city, province=province, k=k,
                             rrf_weight=RRF_WEIGHT, rrf_k=RRF_K)


def get_poi(poi_id: str) -> dict | None:
    """按 poi_id 取 POI；不存在返回 None。"""
    for p in get_store().get_all():
        if p["poi_id"] == poi_id:
            return p
    return None


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """两点球面距离（km）。"""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def search_nearby(
    lat: float,
    lng: float,
    *,
    category: str | None = None,
    radius_km: float = 3.0,
    k: int = 5,
) -> list[dict]:
    """候选 + 距离过滤排序的"周边"检索（数据量小，全量计算即可）。"""
    candidates = [p for p in get_store().get_all(category=category) if p.get("lat") is not None]
    scored = []
    for p in candidates:
        d = _haversine(lat, lng, float(p["lat"]), float(p["lng"]))
        if d <= radius_km:
            scored.append((d, p))
    scored.sort(key=lambda item: item[0])
    return [p for _, p in scored[:k]]
