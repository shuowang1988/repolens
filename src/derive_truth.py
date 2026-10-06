"""
derive_truth.py — 从产物重新推导 Writeup 里出现的每一个数字。

设计原则（本项目已被同一类 bug 烧过五次）：
  检查器**不得**硬编码任何期望结论或期望数字，必须从产物重算，再与文档比对。
  本模块就是唯一的「真值来源」：所有 verify_*.py 与文档数字都必须经它核对。

分两层：
  [core]      便宜、纯内存：语料规模 / 权重表 / 语言命中率 / size 分量下限与跨度
  [overlap]   昂贵、要读 1.81 GB 语料：三种方法的 Top-5 重叠矩阵 + 分歧案例
             昂贵层落盘到 runs/balanced/derived_truth.json，并按输入哈希校验新鲜度；
             校验器默认读缓存但核对指纹，--full 时现场重算。

用法：
  python derive_truth.py            # 重算全部并落盘（慢，几分钟）
  python derive_truth.py --core     # 只重算便宜层并落盘
  python derive_truth.py --print    # 打印已落盘的真值
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent
RUNS = TOOL / "runs" / "balanced"
FEATURES = RUNS / "features.json"
DASHBOARD = RUNS / "dashboard.html"
CORPUS = TOOL / "corpus"
TRUTH_FILE = RUNS / "derived_truth.json"

sys.path.insert(0, str(HERE))
from similarity_v2 import (  # noqa: E402
    WEIGHTS_V2, WEIGHTS_V3_STRUCT, RepoFeatures, similarity_components_v2,
    total_similarity_v3,
)
from repo_structure_similarity import RepoFeatures as F1, total_similarity  # noqa: E402

TOP_K = 5

# 自检 / 校验脚本清单。Writeup 里「N self-test and verification scripts exit zero」
# 这句话的 N 由此列表长度决定，由 verify_writeup_structure.py 核对。
# 实跑命令见 提交清单.md；每个脚本都必须 exit 0。
SELF_TEST_SUITE = [
    "repo_structure_similarity.py",   # v1 特征与相似度自检
    "similarity_v2.py",               # v2/v3 权重与分段 size 自检
    "analyze_failures.py",            # 解释文案回归测试
    "compare_v1_v2.py",               # v1/v2 分量对照
    "diagnose_components.py",         # 分量区分力诊断
    "diag_lang_discrepancy.py",       # 语言判别差异诊断
    "lang_crosscheck.py",             # 跨语言命中率重测
    "corpus_balance.py",              # 语料语言均衡度
    "verify_corpus_state.py",         # 克隆状态文件健壮性
    "verify_disk_guard.py",           # 磁盘上限保护
    "verify_dashboard.py",            # 看板自包含 / 数字 / 披露
    "verify_docs.py",                 # 文档数字 vs 实测产物
    "verify_figures.py",              # 配图数字 vs 实测产物
    "verify_writeup_structure.py",    # 提交稿结构 / 字数 / 逐数字溯源
    "derive_truth.py",                # 真值重算本身
]


# --------------------------------------------------------------------- helpers


def load_features(cache: Path = FEATURES) -> dict:
    data = json.loads(cache.read_text(encoding="utf-8-sig"))
    return {
        s: RepoFeatures(
            name=s, path="", n_files=d["n_files"], n_code_files=d["n_code_files"],
            n_test_files=d["n_test_files"], total_code_lines=d["total_code_lines"],
            max_depth=d.get("max_depth", 0), lang_counts=d["lang_counts"],
            top_level_dirs=set(d["top_level_dirs"]),
            src_to_test_ratio=d["src_to_test_ratio"])
        for s, d in data.items()
    }


def primary_lang(f: RepoFeatures) -> str:
    if not f.lang_counts:
        return "?"
    return max(f.lang_counts.items(), key=lambda kv: kv[1])[0]


def inputs_fingerprint() -> str:
    """输入指纹：特征库 + 三张权重表。任何一项变了，缓存的昂贵层就作废。"""
    h = hashlib.sha256()
    h.update(FEATURES.read_bytes())
    h.update(json.dumps({"v2": WEIGHTS_V2, "v3": WEIGHTS_V3_STRUCT},
                        sort_keys=True).encode())
    return h.hexdigest()[:16]


# ------------------------------------------------------------------ [core] layer


def core_truth(feats: dict | None = None) -> dict:
    feats = feats or load_features()
    slugs = sorted(feats)
    n = len(slugs)
    lang = {s: primary_lang(feats[s]) for s in slugs}
    dist = Counter(lang.values())

    out = {
        "corpus_repos": n,
        "pairwise_combinations": n * (n - 1) // 2,
        "weights_v3_struct": dict(WEIGHTS_V3_STRUCT),
        "weights_v3_sum": round(sum(WEIGHTS_V3_STRUCT.values()), 12),
        "weights_v2": dict(WEIGHTS_V2),
        "lang_distribution": dict(dist.most_common()),
    }

    # ---- 语言分布 + 随机期望（只在 n>=3 的类目上算，与 lang_crosscheck 同口径）
    classes = {l: c for l, c in dist.items() if c >= 3}
    exp = {l: TOP_K * c / n for l, c in classes.items()}
    out["lang_expectation"] = {l: round(v, 4) for l, v in exp.items()}

    # ---- 语言命中率：v3 与 v2 两套权重各算一遍（口径 = 平均每个查询 Top-5 中同语言个数）
    hits = {"v3": {}, "v2": {}}
    for mode in ("v3", "v2"):
        for l in classes:
            members = [s for s in slugs if lang[s] == l]
            per_query = []
            for q in members:
                rows = []
                for s in slugs:
                    if s == q:
                        continue
                    if mode == "v3":
                        sc = total_similarity_v3(feats[q], feats[s])[0]
                    else:
                        sc = sum(WEIGHTS_V2[k] * v for k, v in
                                 similarity_components_v2(feats[q], feats[s]).items())
                    rows.append((s, sc))
                rows.sort(key=lambda r: -r[1])
                top = [s for s, _ in rows[:TOP_K]]
                per_query.append(sum(1 for s in top if lang[s] == l))
            hits[mode][l] = round(sum(per_query) / len(per_query), 4)
    out["lang_hits"] = hits
    # 实测 / 随机期望 的倍数（正文里以「between X and Y」形式引用，必须由真值算出）
    out["lang_ratio"] = {l: round(hits["v3"][l] / exp[l], 4) for l in classes}

    # ---- size 分量：v1 (对数平滑) 下限 / v2 (分段线性) 下限，以及语料规模跨度
    v1, v2 = [], []
    for i, a in enumerate(slugs):
        fa = F1(name=a, path="", n_code_files=feats[a].n_code_files,
                lang_counts=feats[a].lang_counts)
        for b in slugs[i + 1:]:
            fb = F1(name=b, path="", n_code_files=feats[b].n_code_files,
                    lang_counts=feats[b].lang_counts)
            v1.append(total_similarity(fa, fb)[1]["size"])
            v2.append(similarity_components_v2(feats[a], feats[b])["size"])
    out["size_component"] = {
        "v1_min": round(min(v1), 6), "v1_median": round(sorted(v1)[len(v1) // 2], 4),
        "v2_min": round(min(v2), 6), "v2_median": round(sorted(v2)[len(v2) // 2], 4),
    }
    span = sorted(feats[s].n_code_files for s in slugs)
    out["size_span_ratio"] = round(span[-1] / max(1, span[0]), 1)
    out["size_span_files"] = [span[0], span[-1]]

    # ---- 分量统计（v3 定义下的 8 个分量在全部两两组合上的分布）
    comps = {}
    for i, a in enumerate(slugs):
        for b in slugs[i + 1:]:
            for k, v in similarity_components_v2(feats[a], feats[b]).items():
                comps.setdefault(k, []).append(v)
    out["component_stats"] = {
        k: {"min": round(min(v), 6), "median": round(sorted(v)[len(v) // 2], 6),
            "max": round(max(v), 6),
            "frac_lt_0.3": round(sum(1 for x in v if x < 0.3) / len(v), 6)}
        for k, v in comps.items()
    }

    # ---- 看板体积
    if DASHBOARD.exists():
        b = DASHBOARD.stat().st_size
        out["dashboard_bytes"] = b
        out["dashboard_kb"] = round(b / 1024, 1)
    return out


# --------------------------------------------------------------- [overlap] layer


def _readme(slug: str, limit: int = 20000) -> str:
    d = CORPUS / slug.replace("/", "__")
    for name in ("README.md", "README.rst", "README.txt", "README",
                 "readme.md", "Readme.md"):
        p = d / name
        if p.exists() and p.stat().st_size > 0:
            try:
                return p.read_text(encoding="utf-8", errors="ignore")[:limit]
            except OSError:
                return ""
    return ""


def overlap_truth(feats: dict | None = None) -> dict:
    """重算三种方法的 Top-5 重叠矩阵与分歧案例。需要语料在本地。"""
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    feats = feats or load_features()
    slugs = sorted(feats)

    docs, keep = [], []
    for s in slugs:
        t = _readme(s)
        if len(t) >= 200:
            docs.append(t)
            keep.append(s)
    M = TfidfVectorizer(stop_words="english", max_features=20000,
                        sublinear_tf=True, min_df=2).fit_transform(docs)
    C = cosine_similarity(M)
    idx = {s: i for i, s in enumerate(keep)}

    def fntok(slug):
        d = CORPUS / slug.replace("/", "__")
        toks = Counter()
        for f in d.rglob("*"):
            if f.is_file() and ".git" not in f.parts:
                for t in re.split(r"[._-]", f.stem):
                    if len(t) >= 4 and t.isascii():
                        toks[t.lower()] += 1
        return {t for t, n in toks.items() if n < max(3, len(toks) * 0.02)}

    fns = {s: fntok(s) for s in slugs}

    def rank_struct(q):
        r = [(s, total_similarity_v3(feats[q], feats[s])[0])
             for s in slugs if s != q]
        r.sort(key=lambda x: -x[1])
        return [s for s, _ in r[:TOP_K]]

    def rank_content(q):
        if q not in idx:
            return []
        sims = C[idx[q]].copy()
        sims[idx[q]] = -1
        return [keep[i] for i in np.argsort(-sims)[:TOP_K]]

    def rank_fn(q):
        r = []
        for s in slugs:
            if s == q:
                continue
            A, B = fns[s], fns[q]
            r.append((s, len(A & B) / len(A | B) if A and B else 0.0))
        r.sort(key=lambda x: -x[1])
        return [s for s, _ in r[:TOP_K]]

    R = {"struct": {}, "content": {}, "fn": {}}
    for q in slugs:
        R["struct"][q] = set(rank_struct(q))
        R["content"][q] = set(rank_content(q))
        R["fn"][q] = set(rank_fn(q))

    keys = ["struct", "content", "fn"]
    mat = {}
    for a in keys:
        for b in keys:
            vals = []
            for q in slugs:
                ca, cb = R[a].get(q, set()), R[b].get(q, set())
                if not ca or not cb:
                    continue
                vals.append(len(ca & cb) / TOP_K)
            mat[f"{a}|{b}"] = round(float(np.mean(vals)), 6) if vals else 0.0

    def sscore(a, b):
        return round(total_similarity_v3(feats[a], feats[b])[0], 4)

    def cscore(a, b):
        return round(float(C[idx[a]][idx[b]]), 4) if (a in idx and b in idx) else None

    # 分歧案例：结构 Top-5 里排最前、但不在内容 Top-5 的那一个
    case_a, case_b = [], []
    for q in slugs:
        rs, rc = rank_struct(q), rank_content(q)
        if not rc:
            continue
        only = [s for s in rs if s not in set(rc)]
        if only and len(case_a) < 4:
            s = only[0]
            case_a.append({"query": q, "match": s,
                           "struct": sscore(q, s), "content": cscore(q, s),
                           "struct_top5": rs, "content_top5": rc})
        if len(case_b) < 4:
            only_b = [s for s in rc if s not in set(rs)]
            if only_b:
                s = only_b[0]
                case_b.append({"query": q, "match": s,
                               "content": cscore(q, s), "struct": sscore(q, s),
                               "match_in_struct_top5": s in rs})

    out = {"overlap": mat, "repos_with_readme": len(keep),
           "case_a_structure_only": case_a, "case_b_content_only": case_b}

    # 明确记录一个用于正文的具体案例：Textualize/textual -> Textualize/rich
    if "Textualize/textual" in feats and "Textualize/rich" in feats:
        q, s = "Textualize/textual", "Textualize/rich"
        out["named_case"] = {
            "query": q, "match": s,
            "content": cscore(q, s), "struct": sscore(q, s),
            "in_struct_top5": s in R["struct"][q],
            "in_content_top5": s in R["content"][q],
        }
    return out


# ---------------------------------------------------------------------- assemble


def full_truth(do_overlap: bool = True) -> dict:
    feats = load_features()
    t = {"fingerprint": inputs_fingerprint(), "core": core_truth(feats)}
    if do_overlap:
        t["overlap"] = overlap_truth(feats)
    elif TRUTH_FILE.exists():
        try:
            old = json.loads(TRUTH_FILE.read_text(encoding="utf-8"))
            if old.get("fingerprint") == t["fingerprint"] and "overlap" in old:
                t["overlap"] = old["overlap"]
        except (OSError, json.JSONDecodeError):
            pass
    return t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", action="store_true", help="只重算便宜层")
    ap.add_argument("--print", dest="show", action="store_true", help="打印已落盘真值")
    args = ap.parse_args()

    if args.show:
        print(TRUTH_FILE.read_text(encoding="utf-8"))
        return 0

    t = full_truth(do_overlap=not args.core)
    TRUTH_FILE.write_text(json.dumps(t, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(f"已写入 {TRUTH_FILE}")
    print(json.dumps(t, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
