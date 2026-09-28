"""检索评估：加载人工标注查询 → 跑 3 组变体 + k 曲线 → 输出 markdown 报告。

用法（backend 目录下）：
    python -m scripts.eval_retrieval                    # 全部变体
    python -m scripts.eval_retrieval --variant semantic # 只跑一组

变体：
    V1 semantic  走 App 真实路径 search_pois()，含三级粒度兜底（基线）
    V2 keyword   同样的区域过滤候选集，但用字符 bigram 覆盖率排序（去掉 embedding）
    V3 nofilter  不传区域过滤，全国语义检索（测区域过滤值多少分）

指标定义（写死在报告顶部，见 docs）：
    Hit@k    = top-k 至少命中 1 个 gold 的查询占比（用户视角）
    Recall@k = top-k 命中 gold 数 / 该查询 gold 总数，取平均（系统视角）
    MRR      = 平均 1/首个 gold 的排名（未命中记 0）
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
QUERIES = BACKEND / "eval_queries.jsonl"
REPORT = BACKEND / "eval_report.md"

# 无区域的查询（如"海边城市推荐"）App 真实行为是反问用户、不返回结果；
# 这类查询不计入 Hit/Recall，单独作为「行为正确性」检查报告。
NO_REGION_CATEGORIES = {"edge"}


def load_queries(path: Path = QUERIES) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------- 变体实现

def _region_of(q: dict) -> str:
    """App 会从用户消息里抽出的区域名：有城市用城市，否则用省。"""
    return q.get("city") or q.get("province") or ""


def run_semantic(q: dict, k: int) -> list[dict]:
    """V1 基线：**纯语义**（rrf_weight=0），即加混合排序之前的行为。

    必须显式传 0——search_pois 现在默认走 RRF，不钉住的话这个变体会
    跟着线上默认值跑，两边数字一样，对比就失效了。
    """
    return _run_hybrid_with(q, k, 0.0, 10)


_NORM_RE = re.compile(r"[\s，。、？！,.!?·—-]+")


def _bigrams(s: str) -> set[str]:
    s = _NORM_RE.sub("", s)
    return {s[i : i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def run_keyword(q: dict, k: int) -> list[dict]:
    """V2：同样的区域过滤候选集，但按字符 bigram 覆盖率排序（无 embedding）。

    中文查询没有空格分词，所以用 bigram 覆盖率做词法基线——
    这是检索评估里的标准做法，比"按空格切词"对中文公平。
    """
    from app.rag.retriever import _resolve, get_store
    from app.rag.vector_store import _doc_text

    region = _region_of(q)
    if not region:
        return []
    province, city = _resolve(region)
    pool = get_store().get_all(city=city, province=province)
    if not pool:
        return []
    qb = _bigrams(q["query"])
    scored = []
    for poi in pool:
        tb = _bigrams(_doc_text(poi))
        scored.append((len(qb & tb) / max(len(qb), 1), poi))
    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored[:k]]


def _run_hybrid_with(q: dict, k: int, weight: float, rrf_k: int) -> list[dict]:
    """RRF 混合排序（语义排名 + 热度排名融合），指定参数版本。"""
    from app.rag.retriever import _resolve, get_store

    region = _region_of(q)
    if not region:
        return []
    province, city = _resolve(region)
    return get_store().query(q["query"], city=city, province=province, k=k,
                             rrf_weight=weight, rrf_k=rrf_k)


def run_hybrid(q: dict, k: int) -> list[dict]:
    """V4：用 retriever 模块当前配置的 RRF 参数（即线上默认值）。"""
    from app.rag.retriever import RRF_K, RRF_WEIGHT

    return _run_hybrid_with(q, k, RRF_WEIGHT, RRF_K)


def run_rating(q: dict, k: int) -> list[dict]:
    """V0 零假设基线：同样的区域过滤，但完全不看查询内容，只按评分降序。

    没有这条基线，Hit@8 会被高估——单城只有 11~28 个 POI，k=8 时
    随便排都可能命中。语义检索必须**明显赢过它**才算真的有用。
    """
    from app.rag.retriever import _resolve, get_store

    region = _region_of(q)
    if not region:
        return []
    province, city = _resolve(region)
    # text 传空串 → VectorStore.query 内部退化为「metadata 过滤 + rating 降序」
    return get_store().query("", city=city, province=province, k=k)


def run_nofilter(q: dict, k: int) -> list[dict]:
    """V3：全国语义检索，不传区域过滤。"""
    from app.rag.retriever import get_store

    return get_store().query(q["query"], k=k)


VARIANTS = {
    "hybrid": run_hybrid,
    "semantic": run_semantic,
    "keyword": run_keyword,
    "rating": run_rating,
    "nofilter": run_nofilter,
}


# ---------------------------------------------------------------- 指标

def hit_at_k(gold: list[str], results: list[dict], k: int) -> int:
    names = {r["name"] for r in results[:k]}
    return 1 if names & set(gold) else 0


def recall_at_k(gold: list[str], results: list[dict], k: int) -> float:
    if not gold:
        return 0.0
    names = {r["name"] for r in results[:k]}
    return len(names & set(gold)) / len(gold)


def mrr(gold: list[str], results: list[dict]) -> float:
    gs = set(gold)
    for i, r in enumerate(results, start=1):
        if r["name"] in gs:
            return 1.0 / i
    return 0.0


def evaluate(queries: list[dict], variant: str, k: int) -> dict:
    fn = VARIANTS[variant]
    rows = []
    for q in queries:
        try:
            results = fn(q, k)
        except Exception as exc:  # 单条失败不中断整轮
            results = []
            print(f"  ! {q['id']} 执行失败: {exc}")
        rows.append({
            "id": q["id"],
            "category": q["category"],
            "query": q["query"],
            "gold": q["gold"],
            # 无区域查询对任何变体都无解（都返回空），统一排除，否则会不公平地拉低某些变体
            "expect_empty": not _region_of(q),
            "hit": hit_at_k(q["gold"], results, k),
            "recall": recall_at_k(q["gold"], results, k),
            "mrr": mrr(q["gold"], results),
            "names": [r["name"] for r in results[:k]],
        })
    return {"variant": variant, "k": k, "rows": rows}


def mean(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def aggregate(result: dict) -> dict:
    """按 category 分组求均值；expect_empty 的查询不计入主指标。"""
    scored = [r for r in result["rows"] if not r["expect_empty"]]
    by_cat = defaultdict(list)
    for r in scored:
        by_cat[r["category"]].append(r)
    return {
        "overall": {
            "n": len(scored),
            "hit": mean(r["hit"] for r in scored),
            "recall": mean(r["recall"] for r in scored),
            "mrr": mean(r["mrr"] for r in scored),
        },
        "by_category": {
            c: {"n": len(rs), "hit": mean(r["hit"] for r in rs),
                "recall": mean(r["recall"] for r in rs), "mrr": mean(r["mrr"] for r in rs)}
            for c, rs in sorted(by_cat.items())
        },
        "empty_checks": [r for r in result["rows"] if r["expect_empty"]],
    }


def sweep(queries: list[dict], k: int) -> None:
    """网格搜索 RRF 的 weight × rrf_k，打印完整表格（不只报最好那组）。"""
    from app.rag.retriever import get_store

    get_store()  # 预热：加载 BGE
    weights = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5]
    rrf_ks = [5, 10, 20]
    cats = ["semantic", "city", "province", "alias", "edge"]

    # 基线：纯语义（w=0）与纯热度
    base = {}
    for name, fn in (("pure_semantic", lambda q, kk: _run_hybrid_with(q, kk, 0.0, 10)),
                     ("pure_rating", run_rating)):
        rows = [{"category": q["category"], "hit": hit_at_k(q["gold"], r := fn(q, k), k),
                 "recall": recall_at_k(q["gold"], r, k), "mrr": mrr(q["gold"], r)}
                for q in queries if _region_of(q)]
        base[name] = rows

    print("=" * 100)
    print(f"{'w':>5} {'K':>4} | {'Hit@'+str(k):>8} {'Recall@'+str(k):>9} {'MRR':>7} | "
          + " ".join(f"{c:>9}" for c in cats))
    print("-" * 100)

    def line(w, rk, rows):
        agg = lambda rs, key: mean(r[key] for r in rs)
        perc = lambda rs, key: {
            c: mean(r[key] for r in rs if r["category"] == c) for c in cats
        }
        p = perc(rows, "recall")
        print(f"{w:>5} {rk:>4} | {_pct(agg(rows,'hit')):>8} {_pct(agg(rows,'recall')):>9} "
              f"{agg(rows,'mrr'):>7.3f} | " + " ".join(f"{_pct(p[c]):>9}" for c in cats))

    for nm, rows in base.items():
        print(f"{nm:>10} 基线:")
        line("--", "--", rows)

    print("-" * 100)
    for w in weights:
        for rk in rrf_ks:
            rows = [{"category": q["category"],
                     "hit": hit_at_k(q["gold"], r := _run_hybrid_with(q, k, w, rk), k),
                     "recall": recall_at_k(q["gold"], r, k),
                     "mrr": mrr(q["gold"], r)}
                    for q in queries if _region_of(q)]
            line(w, rk, rows)
    print("=" * 100)
    print("表格列 = 各类别 Recall@k。基线行 w=-- 为对照，不是网格点。")
    print("注意：50 条查询上做网格搜索有过拟合风险，最优组未必泛化。")


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              cwd=BACKEND, capture_output=True, text=True,
                              timeout=5).stdout.strip() or "(unknown)"
    except Exception:
        return "(unknown)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=[*VARIANTS, "all"], default="all")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--sweep", action="store_true",
                    help="网格搜索 RRF 参数（weight × rrf_k），只打印表格")
    args = ap.parse_args()

    queries = load_queries()

    if args.sweep:
        return sweep(queries, args.k)

    variants = list(VARIANTS) if args.variant == "all" else [args.variant]

    from app.rag.embeddings import MODEL_ID
    from app.rag.retriever import get_store

    store = get_store()
    corpus_n = store.count()

    print(f"语料 {corpus_n} 条 · 查询 {len(queries)} 条 · 模型 {MODEL_ID}")
    results = {}
    for v in variants:
        print(f"跑 {v} (k={args.k}) ...")
        results[v] = evaluate(queries, v, args.k)

    # k 曲线只跑 semantic（证明默认 k=8 是测出来的）
    curve = {}
    if args.variant == "all":
        for k in (3, 5, 8, 10):
            print(f"跑 hybrid k={k} ...")
            curve[k] = aggregate(evaluate(queries, "hybrid", k))

    # ------------------------------------------------------------ 报告
    L: list[str] = []
    L.append("# 检索评估报告（自动生成，勿手改）\n")
    L.append(f"- 语料：**{corpus_n} 条** POI（全国 34 省级行政区）")
    L.append(f"- 查询：**{len(queries)} 条**人工标注（city 20 / semantic 15 / province 5 / alias 5 / edge 5）")
    L.append(f"- 嵌入模型：`{MODEL_ID}`（512 维，CPU）")
    L.append(f"- 脚本 commit：`{_commit()}`")
    L.append(f"- 复现：`python -m scripts.eval_retrieval`\n")
    L.append("## 指标定义\n")
    L.append("```")
    L.append("Hit@k    = top-k 至少命中 1 个 gold 的查询占比       （用户视角：给的东西里有没有对的）")
    L.append("Recall@k = top-k 命中 gold 数 / 该查询 gold 总数，取平均（系统视角：候选够不够覆盖正确答案）")
    L.append("MRR      = 平均 1/首个 gold 的排名（未命中记 0）      （排序质量）")
    L.append("```\n")

    L.append(f"## 主结果（k={args.k}）\n")
    L.append("| 变体 | 说明 | Hit@%d | Recall@%d | MRR |" % (args.k, args.k))
    L.append("|---|---|---|---|---|")
    desc = {"hybrid": "**线上默认**：区域过滤 + RRF 混合排序（语义排名 × 热度排名）",
            "rating": "**零假设基线**：同区域过滤，仅按评分降序（不看查询内容）",
            "semantic": "**改动前基线**：区域过滤 + 纯 BGE 语义检索（不含热度融合）",
            "keyword": "同样的区域过滤候选，bigram 词法排序（去掉 embedding）",
            "nofilter": "全国语义检索，不做区域过滤"}
    for v, res in results.items():
        a = aggregate(res)["overall"]
        L.append(f"| **{v}** | {desc[v]} | {_pct(a['hit'])} | {_pct(a['recall'])} | {a['mrr']:.3f} |")
    L.append("")

    for v, res in results.items():
        agg = aggregate(res)
        L.append(f"### {v} · 分类别\n")
        L.append("| 类别 | 条数 | Hit@%d | Recall@%d | MRR |" % (args.k, args.k))
        L.append("|---|---|---|---|---|")
        for c, a in agg["by_category"].items():
            L.append(f"| {c} | {a['n']} | {_pct(a['hit'])} | {_pct(a['recall'])} | {a['mrr']:.3f} |")
        L.append("")
        if agg["empty_checks"]:
            L.append("无区域查询（App 真实行为=反问用户、不返回结果，不计入主指标）：\n")
            for r in agg["empty_checks"]:
                L.append(f"- `{r['query']}` → 返回 {len(r['names'])} 条 "
                         f"{'✅ 行为正确' if not r['names'] else '⚠️ 未按预期返回空'}")
            L.append("")

    if curve:
        L.append("## k 曲线（hybrid 线上变体）\n")
        L.append("| k | Hit@k | Recall@k | MRR |")
        L.append("|---|---|---|---|")
        for k, a in curve.items():
            o = a["overall"]
            L.append(f"| {k} | {_pct(o['hit'])} | {_pct(o['recall'])} | {o['mrr']:.3f} |")
        L.append("")

    # 失败案例
    primary = "hybrid" if "hybrid" in results else variants[0]
    L.append(f"## 失败案例（{primary} 变体 top-k 全 miss）\n")
    misses = [r for r in results[primary]["rows"]
              if not r["expect_empty"] and r["hit"] == 0]
    if not misses:
        L.append("无。\n")
    else:
        for r in misses:
            L.append(f"**{r['id']}** [{r['category']}] `{r['query']}`")
            L.append(f"- gold：{'、'.join(r['gold'])}")
            L.append(f"- 实际返回：{'、'.join(r['names']) or '(空)'}")
            L.append("")
    # 低召回（命中了但覆盖不全）
    partial = [r for r in results[primary]["rows"]
               if not r["expect_empty"] and r["hit"] == 1 and r["recall"] < 0.5]
    if partial:
        L.append("## 部分命中（Recall < 50%）\n")
        for r in partial:
            got = set(r["names"]) & set(r["gold"])
            L.append(f"- `{r['query']}` 命中 {len(got)}/{len(r['gold'])}：{'、'.join(sorted(got))}")
        L.append("")

    report = "\n".join(L) + "\n"
    REPORT.write_text(report, encoding="utf-8")
    print(f"\n报告已写入 {REPORT}")
    print()
    for v, res in results.items():
        a = aggregate(res)["overall"]
        print(f"  {v:9s} n={a['n']:3d}  Hit@{args.k}={_pct(a['hit'])}  "
              f"Recall@{args.k}={_pct(a['recall'])}  MRR={a['mrr']:.3f}")


if __name__ == "__main__":
    main()
