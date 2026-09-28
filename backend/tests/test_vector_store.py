from pathlib import Path

from app.rag.ingest import load_corpus
from app.rag.vector_store import VectorStore

from conftest import FakeEmbedder


def _poi(i: int, city: str = "北京", province: str = "北京", category: str = "attraction", name: str = "景点", rating: float = 4.5, tags=None) -> dict:
    return {
        "poi_id": f"test-{i:03d}", "province": province, "city": city, "name": name,
        "category": category, "rating": rating, "price_tier": 2,
        "lat": 39.9, "lng": 116.4, "description": f"第{i}个测试点",
        "tags": tags or ["测试"],
    }


def test_upsert_and_count(tmp_path):
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    assert store.count() == 0
    n = store.upsert_pois([_poi(1), _poi(2)])
    assert n == 2 and store.count() == 2
    # 重复 upsert 幂等（同一 poi_id 覆盖）
    store.upsert_pois([_poi(1)])
    assert store.count() == 2


def test_query_by_city_and_category(tmp_path):
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    store.upsert_pois([
        _poi(1, city="北京", category="attraction", name="故宫博物院"),
        _poi(2, city="北京", category="restaurant", name="全聚德烤鸭"),
        _poi(3, city="成都", category="restaurant", name="蜀大侠火锅"),
    ])
    hits = store.query("故宫", city="北京", category="attraction", k=5)
    assert [p["poi_id"] for p in hits] == ["test-001"]
    hits2 = store.query("火锅", city="成都")
    assert hits2 and hits2[0]["poi_id"] == "test-003"


def test_query_empty_text_sorts_by_rating(tmp_path):
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    store.upsert_pois([
        _poi(1, name="普通景点", rating=4.0),
        _poi(2, name="高分景点", rating=4.9),
    ])
    hits = store.query("", city="北京", category="attraction", k=5)
    assert hits[0]["poi_id"] == "test-002"  # rating 高者在前


def test_rrf_zero_is_backward_compatible(tmp_path):
    """rrf_weight=0（默认）必须与加混合排序之前的行为逐位一致。"""
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    store.upsert_pois([
        _poi(1, name="故宫博物院", rating=4.0),
        _poi(2, name="天安门广场", rating=4.9),
    ])
    assert (store.query("故宫", city="北京", k=2)
            == store.query("故宫", city="北京", k=2, rrf_weight=0.0))


def test_rrf_blends_semantic_and_rating(tmp_path):
    """RRF 的两端行为：权重为 0 看语义，权重极大退化为看评分。

    语料：语义最强（名字含"故宫"）的评分最低，评分最高的语义最弱——
    这样两个端点必然给出**相反**的排序，能证明融合真的在起作用。
    """
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    store.upsert_pois([
        _poi(1, name="故宫博物院", rating=4.0),   # 语义强、评分低
        _poi(2, name="天安门广场", rating=4.9),   # 语义弱、评分高
    ])
    pure = store.query("故宫", city="北京", k=2, rrf_weight=0.0)
    assert pure[0]["poi_id"] == "test-001"        # 纯语义：含"故宫"的在前

    heavy = store.query("故宫", city="北京", k=2, rrf_weight=1000.0)
    assert heavy[0]["poi_id"] == "test-002"       # 权重极大：高评分仅剩热度项主导


def test_rrf_only_applies_to_text_queries(tmp_path):
    """空查询本就按评分降序，rrf_weight 不应改变它。"""
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    store.upsert_pois([
        _poi(1, name="普通景点", rating=4.0),
        _poi(2, name="高分景点", rating=4.9),
    ])
    assert ([p["poi_id"] for p in store.query("", city="北京", k=2)]
            == [p["poi_id"] for p in store.query("", city="北京", k=2, rrf_weight=5.0)])


def test_rrf_does_not_change_candidate_pool(tmp_path):
    """融合只影响 top-k 的挑选与排序，不改变区域过滤出的候选池。

    注意：k 小于候选池时，两者**选出的子集本来就可以不同**——
    所以这里让 k 覆盖整个池，断言集合一致、只是顺序可能变。
    """
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    store.upsert_pois([_poi(i, name=f"景点{i}", rating=4.0 + i * 0.1) for i in range(1, 8)])
    pure = [p["poi_id"] for p in store.query("景点", city="北京", k=7, rrf_weight=0.0)]
    fused = [p["poi_id"] for p in store.query("景点", city="北京", k=7, rrf_weight=0.75)]
    assert sorted(pure) == sorted(fused)          # 候选池一致
    assert len(store.get_all(city="北京")) == 7   # 过滤层不受排序参数影响


def test_get_all_and_poi_shape(tmp_path):
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    store.upsert_pois([_poi(1, tags=["历史", "免费"]), _poi(2, city="成都", province="四川")])
    all_pois = store.get_all()
    assert len(all_pois) == 2
    first = all_pois[0]
    required = {"poi_id", "province", "city", "name", "category", "rating",
                "price_tier", "lat", "lng", "description", "tags"}
    assert set(first) == required
    assert first["tags"] == ["历史", "免费"]  # tags 恢复为 list
    assert store.get_all(city="成都")[0]["poi_id"] == "test-002"


def test_poi_dict_contains_province(tmp_path):
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    store.upsert_pois([_poi(1, city="广州", province="广东")])
    assert store.get_all()[0]["province"] == "广东"


def test_query_by_province(tmp_path):
    """province 过滤：广东查询只返回广东条目，不返回其他省。"""
    fixture = Path(__file__).parent / "fixtures" / "sample_pois.jsonl"
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    store.upsert_pois(load_corpus(fixture))
    hits = store.query("", province="广东", k=10)
    assert len(hits) == 4
    assert {p["province"] for p in hits} == {"广东"}
    assert len(store.get_all(province="广东")) == 4


def test_get_all_tolerates_legacy_row_without_province(tmp_path):
    """旧 schema 持久化的行缺 province 键：get_all 不崩溃且回退为空串。"""
    store = VectorStore(str(tmp_path / "chroma"), FakeEmbedder())
    store.upsert_pois([_poi(1)])
    # 模拟 Task 2 之前旧 schema 写入的行：记录中没有 province 键
    store.upsert_pois([{
        "poi_id": "legacy-001", "city": "北京", "name": "旧景点",
        "category": "attraction", "rating": 4.0, "price_tier": 2,
        "lat": 39.9, "lng": 116.4, "description": "旧数据",
    }])
    by_id = {p["poi_id"]: p for p in store.get_all()}
    assert set(by_id) == {"test-001", "legacy-001"}
    assert by_id["legacy-001"]["province"] == ""
