"""diagnose_components.py — 用真实语料统计 5 个分量的实际分布。

回答一个问题：**哪些分量在真正起区分作用，哪些已经退化成"恒为 1"？**
退化分量不只是浪费权重，还会让总分虚高——必须拿证据说话。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from analyze_failures import diagnose  # noqa: E402
from repo_structure_similarity import WEIGHTS, RepoFeatures, total_similarity  # noqa: E402


def load(cache: Path) -> dict[str, RepoFeatures]:
    data = json.loads(cache.read_text(encoding="utf-8-sig"))
    out = {}
    for slug, d in data.items():
        out[slug] = RepoFeatures(
            name=slug, path="", n_files=d["n_files"], n_code_files=d["n_code_files"],
            n_test_files=d["n_test_files"], n_dirs=d.get("n_dirs", 0),
            total_code_lines=d["total_code_lines"], max_depth=d.get("max_depth", 0),
            lang_counts=d["lang_counts"], top_level_dirs=set(d["top_level_dirs"]),
            path_segments=d.get("path_segments", {}),
            test_path_ratio=d.get("test_path_ratio", 0.0),
            src_to_test_ratio=d["src_to_test_ratio"],
        )
    return out


feats = load(Path("..") / "runs" / "demo" / "features.json")
print(f"语料 {len(feats)} 个仓库\n")

rep = diagnose(feats)
print("=" * 78)
print(f"全部 {rep['n_pairs']} 个两两组合的分量分布")
print("=" * 78)
print(f"{'分量':14s}{'权重':>7s}{'最小':>9s}{'中位':>9s}{'最大':>9s}{'>0.9占比':>11s}{'<0.3占比':>11s}")
print("-" * 78)
for k, v in rep["components"].items():
    print(f"{k:14s}{v['weight']:>7.2f}{v['min']:>9.3f}{v['p50']:>9.3f}{v['max']:>9.3f}"
          f"{v['frac_above_0.9']:>11.3f}{v['frac_below_0.3']:>11.3f}")

print("\n" + "=" * 78)
print("诊断")
print("=" * 78)
for k, v in rep["components"].items():
    if v["frac_above_0.9"] > 0.85:
        print(f"  [退化] {k:14s} {v['frac_above_0.9']*100:.0f}% 的组合 >0.9 —— 几乎没有区分力")
    elif v["frac_below_0.3"] > 0.5:
        print(f"  [稀疏] {k:14s} {v['frac_below_0.3']*100:.0f}% 的组合 <0.3 —— 只在少数情况起作用")
    else:
        print(f"  [有效] {k:14s} 分布跨度 {v['min']:.2f}~{v['max']:.2f}")

# 权重再分配建议
print("\n" + "=" * 78)
print("按实际区分力重分配权重的建议")
print("=" * 78)
spread = {}
for k, v in rep["components"].items():
    spread[k] = v["max"] - v["min"]
tot = sum(spread.values())
if tot > 0:
    new_w = {k: round(spread[k] / tot * 1.0, 3) for k in spread}
    for k in WEIGHTS:
        old = WEIGHTS[k]
        mark = "  <-- 建议调整" if abs(new_w[k] - old) > 0.05 else ""
        print(f"  {k:14s} 现权重 {old:.2f} -> 建议 {new_w[k]:.3f}{mark}")
    print("\n  注：这是按「区分跨度」等比分配，是一个起点，不是最优解。")
    print("  真正的调权需要在有标注的数据集上做——本项目没有标注，故只作为诊断披露。")
