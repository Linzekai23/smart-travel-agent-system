"""向量库封装：JSON 记录 + .npy 向量矩阵 + numpy 余弦检索（自建，不用 Chroma）。

- 存储：backend/data/chroma/ 目录下 pois.json + embeddings.npy
  （env CHROMA_PERSIST_DIR 沿用旧名可覆盖——历史文档/脚本不破）
- 检索：查询向量与候选点积（BGE 与 FakeEmbedder 均 L2 归一化 → 点积即余弦），
  city/province/category 过滤后取 top-k；1054 条规模毫秒级
- 文档文本：name + description + tags + category + province + city 聚合（检索语义的来源）
- 为什么不用 Chroma：chromadb 1.5.x 在本机（Windows + Python 3.14）新建/增量库的
  HNSW 索引从不落盘（segment 只有 index_metadata.pickle，无 bin），任何新进程查询报
  "Error loading hnsw index"（2026-08-27 实测回归，1.4.1 同样失败，写入路径彻底坏）。
  自建实现无二进制依赖、无后台 compactor，进程重启后查询确定性可用。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

# 输出 POI dict 的固定字段集合（get_all/query 的契约，测试断言依赖）
OUTPUT_FIELDS = ("poi_id", "province", "city", "name", "category", "rating",
                 "price_tier", "lat", "lng", "description", "tags")


def _doc_text(p: dict) -> str:
    tags = "、".join(p.get("tags", []))
    return (f"{p['name']}。{p.get('description', '')}。标签：{tags}。"
            f"类别：{p['category']}。省份：{p.get('province', '')}。城市：{p['city']}")


def _poi_dict(record: dict) -> dict:
    """规范化输出：province 缺省为空串（兼容旧 schema 行）、tags 还原为 list。"""
    d = {k: record.get(k) for k in OUTPUT_FIELDS}
    d["province"] = record.get("province") or ""
    tags = record.get("tags") or []
    d["tags"] = list(tags) if isinstance(tags, list) else [str(tags)]
    return d


class VectorStore:
    """自建持久化向量库：按 poi_id 幂等 upsert；进程内加载全量（千条级毫秒检索）。"""

    def __init__(self, persist_dir: str, embedder) -> None:
        self._dir = Path(persist_dir)
        self._embedder = embedder
        self._records: dict[str, dict] = {}
        self._matrix: np.ndarray | None = None
        self._load()

    # ---------- 持久化 ----------

    def _load(self) -> None:
        """从磁盘加载记录与向量；文件缺失（首次运行）→ 空库。"""
        records_path = self._dir / "pois.json"
        mat_path = self._dir / "embeddings.npy"
        if not records_path.exists():
            return
        try:
            records = json.loads(records_path.read_text(encoding="utf-8"))
            mat = np.load(mat_path)
        except (OSError, ValueError, json.JSONDecodeError):
            raise RuntimeError(
                f"向量库文件损坏：{self._dir}。请重新执行 python -m app.rag.ingest"
            )
        if not isinstance(records, list) or len(records) != mat.shape[0]:
            raise RuntimeError(
                f"向量库记录与向量矩阵不对齐：{self._dir}。请重新执行 python -m app.rag.ingest"
            )
        self._records = {p["poi_id"]: p for p in records}
        self._matrix = mat

    def _save(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        records = list(self._records.values())
        rows = self._matrix if self._matrix is not None else np.zeros((0, 1), dtype="float32")
        tmp_json = self._dir / "pois.json.tmp"
        tmp_npy = self._dir / "embeddings.tmp.npy"  # np.save 自动补 .npy，临时名须以 .npy 结尾
        tmp_json.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        np.save(tmp_npy, rows)
        tmp_json.replace(self._dir / "pois.json")
        tmp_npy.replace(self._dir / "embeddings.npy")

    # ---------- 公开接口（与旧 Chroma 版签名一致） ----------

    def upsert_pois(self, pois: list[dict]) -> int:
        """幂等入库：同一 poi_id 覆盖；返回条数。"""
        if not pois:
            return 0
        dim = self._matrix.shape[1] if self._matrix is not None else None
        changed = [p for p in pois if p["poi_id"] not in self._records
                   or _doc_text(p) != _doc_text(self._records[p["poi_id"]])]
        if changed:
            vectors = self._embedder.embed([_doc_text(p) for p in changed])
            if dim is None:
                dim = len(vectors[0])
                self._matrix = np.zeros((0, dim), dtype="float32")
            if dim != len(vectors[0]):
                raise RuntimeError(
                    f"embedding 维数变化（{dim} → {len(vectors[0])}）：模型被替换。"
                    "请删除向量库目录后重新执行 python -m app.rag.ingest"
                )
            idx = {pid: i for i, pid in enumerate(self._records)}
            for p, vec in zip(changed, vectors):
                if p["poi_id"] in idx:
                    self._matrix[idx[p["poi_id"]]] = np.asarray(vec, dtype="float32")
                else:
                    idx[p["poi_id"]] = self._matrix.shape[0]
                    self._matrix = np.vstack([self._matrix, np.asarray(vec, dtype="float32")])
            self._records.update({p["poi_id"]: p for p in changed})
            self._save()
        return len(pois)

    def query(
        self,
        text: str,
        *,
        city: str | None = None,
        province: str | None = None,
        category: str | None = None,
        k: int = 10,
        rrf_weight: float = 0.0,
        rrf_k: int = 10,
    ) -> list[dict]:
        """向量检索；text 为空时退化为 metadata 过滤 + rating 降序。

        rrf_weight > 0 时启用 RRF 混合排序（语义排名 + 热度排名倒数融合）：
        余弦相似度与 rating 量纲不可比，RRF 只用**排名**、免归一化。
        rrf_weight = 0（默认）即纯语义，与旧行为完全一致。
        依据见 docs/retrieval-eval.md：纯语义在"著名景点"类查询上会输给评分排序。
        """
        indices = self._filter_indices(city, province, category)
        if text.strip():
            if self._matrix is None or not indices:
                return []
            q = np.asarray(self._embedder.embed_query(text), dtype="float32")
            scores = self._matrix[indices] @ q  # L2 归一化向量 → 点积即余弦
            if rrf_weight > 0:
                order = self._rrf_order(indices, scores, k, rrf_weight, rrf_k)
            else:
                order = np.argsort(-scores)[:k]
            return [_poi_dict(self._records[pid]) for pid in (self._ids()[indices][order])]
        order = sorted(indices,
                       key=lambda i: float(self._records[self._ids()[i]].get("rating") or 0),
                       reverse=True)[:k]
        return [_poi_dict(self._records[self._ids()[i]]) for i in order]

    def _rrf_order(self, indices, scores, k: int, weight: float, rrf_k: int):
        """RRF：1/(K+语义排名) + weight/(K+热度排名)，返回 top-k 的局部下标。"""
        ids = self._ids()
        n = len(indices)
        sem_rank = np.empty(n, dtype="int64")
        sem_rank[np.argsort(-scores)] = np.arange(n)
        ratings = np.array(
            [float(self._records[ids[i]].get("rating") or 0) for i in indices],
            dtype="float64",
        )
        rat_rank = np.empty(n, dtype="int64")
        rat_rank[np.argsort(-ratings)] = np.arange(n)
        fused = 1.0 / (rrf_k + sem_rank + 1) + weight / (rrf_k + rat_rank + 1)
        return np.argsort(-fused)[:k]

    def get_all(
        self,
        city: str | None = None,
        province: str | None = None,
        category: str | None = None,
    ) -> list[dict]:
        """全量（可过滤）POI 列表；无 Chroma 1000 条上限。"""
        indices = self._filter_indices(city, province, category)
        ids = self._ids()
        return [_poi_dict(self._records[ids[i]]) for i in indices]

    def count(self) -> int:
        return len(self._records)

    # ---------- 内部 ----------

    def _ids(self) -> np.ndarray:
        """与 _matrix 行对齐的 poi_id 数组。"""
        if not hasattr(self, "_ids_cache") or self._ids_cache is None or len(self._ids_cache) != len(self._records):
            self._ids_cache = np.array(list(self._records.keys()))
        return self._ids_cache

    def _filter_indices(self, city: str | None, province: str | None, category: str | None) -> list[int]:
        """按 city/province/category 过滤出记录下标（顺序 = 入库顺序）。"""
        ids = self._ids()
        out = []
        for i, pid in enumerate(ids):
            p = self._records[pid]
            if province and p.get("province") != province:
                continue
            if city and p.get("city") != city:
                continue
            if category and p.get("category") != category:
                continue
            out.append(i)
        return out
