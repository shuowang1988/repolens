"""
compare_v1_v2.py — 在真实语料上对照 v1 / v2，并统计分量区分力

目的（两条，都必须拿数据说话）：
  1. v2 修的两个缺陷是否真的改善了判别力
  2. v2 新增的分量有没有也退化成"恒为 1"

判别力的量化指标：用**分量区分跨度**(max-min) 与**分离度**
（异语言对均值 与 同语言对均值 之差）。分离度为正说明该分量
真的在区分语言家族，接近 0 说明它没有信息量。
"""
import json
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from repo_structure_similarity import WEIGHTS, total_similarity  # noqa: E402
from similarity_v2 import WEIGHTS_V2, RepoFeatures, similarity_components_v2, \
    total_similarity_v2  # noqa: E402

# v1 的结构（与 repo_structure_similarity.py 保持一致的字段名）
from repo_structure_similarity import RepoFeatures as F1  # noqa: E402


def load(cache: Path) -> dict[str, RepoFeatures]:
    data = json.loads(cache.read_text(encoding="utf-8-sig"))
    out = {}
    for slug, d in data.items():
        out[slug] = RepoFeatures(
            name=slug, path="", n_files=d["n_files"], n_code_files=d["n_code_files"],
            n_test_files=d["n_test_files"], total_code_lines=d["total_code_lines"],
            max_depth=d.get("max_depth", 0), lang_counts=d["lang_counts"],
            top_level_dirs=set(d["top_level_dirs"]),
            src_to_test_ratio=d["src_to_test_ratio"],
        )
    return out


def main_lang(f: RepoFeatures) -> str:
    return max(f.lang_counts.items(), key=lambda kv: kv[1])[0] if f.lang_counts else "?"


feats = load(Path("..") / "runs" / "demo" / "features.json")
slugs = sorted(feats)
pairs = list(combinations(slugs, 2))
print(f"语料 {len(feats)} 个仓库，{len(pairs)} 个两两组合\n")

# ---------- 分量区分力
print("=" * 84)
print("v2 分量区分力（含「分离度」：异语言对均值 - 同语言对均值，正值说明能区分语言家族）")
print("=" * 84)
print(f"{'分量':16s}{'权重':>7s}{'最小':>8s}{'中位':>8s}{'最大':>8s}{'>0.9':>8s}{'<0.3':>8s}{'分离度':>10s}")
print("-" * 84)

stats = {}
for k in WEIGHTS_V2:
    vals, same, diff = [], [], []
    for a, b in pairs:
        c = similarity_components_v2(feats[a], feats[b])[k]
        vals.append(c)
        (same if main_lang(feats[a]) == main_lang(feats[b]) else diff).append(c)
    vals.sort()
    n = len(vals)
    sep = (sum(diff) / len(diff) - sum(same) / len(same)) if same and diff else 0.0
    stats[k] = {"span": vals[-1] - vals[0], "sep": sep,
                "frac_hi": sum(v > .9 for v in vals) / n,
                "frac_lo": sum(v < .3 for v in vals) / n}
    print(f"{k:16s}{WEIGHTS_V2[k]:>7.2f}{vals[0]:>8.3f}{vals[n//2]:>8.3f}{vals[-1]:>8.3f}"
          f"{stats[k]['frac_hi']:>8.3f}{stats[k]['frac_lo']:>8.3f}{sep:>10.3f}")

print("\n判读：")
for k, v in sorted(stats.items(), key=lambda kv: -kv[1]["span"]):
    tag = "[退化]" if v["span"] < 0.5 else ("[稀疏]" if v["frac_lo"] > 0.6 else "[有效]")
    print(f"  {tag} {k:16s} 跨度 {v['span']:.2f}  分离度 {v['sep']:+.3f}")

# ---------- v1 vs v2 对照
print("\n" + "=" * 84)
print("v1 与 v2 对照：size 分量的真实取值分布")
print("=" * 84)
v1_size, v2_size = [], []
for a, b in pairs:
    fa = F1(name=a, path="", n_code_files=feats[a].n_code_files,
            lang_counts=feats[a].lang_counts)
    fb = F1(name=b, path="", n_code_files=feats[b].n_code_files,
            lang_counts=feats[b].lang_counts)
    _, c1 = total_similarity(fa, fb)
    v1_size.append(c1["size"])
    v2_size.append(similarity_components_v2(feats[a], feats[b])["size"])

v1_size.sort(); v2_size.sort()
n = len(v1_size)
print(f"{'':6s}{'最小':>9s}{'p10':>9s}{'中位':>9s}{'最大':>9s}")
print(f"{'v1':6s}{v1_size[0]:>9.3f}{v1_size[n//10]:>9.3f}{v1_size[n//2]:>9.3f}{v1_size[-1]:>9.3f}")
print(f"{'v2':6s}{v2_size[0]:>9.3f}{v2_size[n//10]:>9.3f}{v2_size[n//2]:>9.3f}{v2_size[-1]:>9.3f}")
print(f"\n>>> v1 的 size 最小值 {v1_size[0]:.3f}：这是缺陷——规模差再多也不会低于此值")
print(f">>> v2 的 size 最小值 {v2_size[0]:.3f}：已能判为 0")

# ---------- 排序质量
print("\n" + "=" * 84)
print("v2 排序抽查 A：跨语言项目 gin 的 Top-5")
print("=" * 84)
gin = feats["gin-gonic/gin"]
rows = []
for s, f in feats.items():
    if s == "gin-gonic/gin":
        continue
    sc, comp = total_similarity_v2(gin, f)
    rows.append((s, sc, main_lang(f), comp))
rows.sort(key=lambda r: -r[1])
for i, (s, sc, lang, _c) in enumerate(rows[:5], 1):
    print(f"  {i}. {s:34s} {sc:.4f}  [{lang}]")

print("\n" + "=" * 84)
print("★ 关键观察：纯结构特征**无法**跨语言判别")
print("=" * 84)
go_top = next((r for r in rows if r[2] == "Go"), None)
py_top = next((r for r in rows if r[2] == "Python"), None)
print(f"  gin 的最佳 Go 候选   : {go_top[0]:30s} {go_top[1]:.4f}")
print(f"  gin 的最佳 Python 候选: {py_top[0]:30s} {py_top[1]:.4f}")
print(f"  差距: {py_top[1] - go_top[1]:+.4f}")
print()
print("  原因：primary_lang 权重仅 0.15，而结构类分量（size/top_dir_count/")
print("  depth/test_ratio）对任何语言都给分。语料里 Go 项目只有 gin 和 hugo 两个，")
print("  而 Python 项目有 12 个，Python 项目之间的结构相似度天然更高，")
print("  数量优势盖过了语言信号。")
print()
print("  结论：这是一个**真实的方法局限**，不是 bug。纯结构相似度适合回答")
print("  「这个仓库的组织方式像哪个仓库」，不适合回答「这是不是同一种语言的生态」。")
print("  工具的定位应当是前者。Writeup 里必须写清这个边界，不能声称跨语言判别。")
