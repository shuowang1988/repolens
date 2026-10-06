"""
analyze_failures.py — 相似度分数的「零信息检验」

这轮真实跑完 19 个仓库后暴露了一个**必须写进 Writeup 的负面发现**：

    代码规模接近（1170 vs 84 个代码文件）        ← 这说明什么？
    代码规模接近（1170 vs 3049 个代码文件）      ← 这也说明「接近」？
    代码规模接近（54 vs 469 个代码文件）         ← 差了近 9 倍也叫接近？

**问题：`explain()` 的文案是硬编码的，没有按实际差距说话。**
1170 与 84、1170 与 3049 都输出「代码规模接近」，这在 Clarity 评分上是硬伤，
而且会误导读者以为方法在正常工作。

本模块做两件事：
  1. 诊断：统计各分量的实际分布，找出「几乎恒为 1」的退化分量
  2. 修正：按真实差距生成分级文案，并把分量值一并给出

【为什么先诊断再修】符合用户的既定规矩：不轻信二手结论，先拿证据再定案。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from repo_structure_similarity import WEIGHTS, RepoFeatures, total_similarity  # noqa: E402


def diagnose(features: dict[str, RepoFeatures]) -> dict:
    """统计每个分量在全部两两组合上的分布。"""
    slugs = sorted(features)
    pairs = []
    for i, a in enumerate(slugs):
        for b in slugs[i + 1:]:
            _, comp = total_similarity(features[a], features[b])
            pairs.append(comp)

    n = len(pairs)
    report = {"n_pairs": n, "components": {}}
    for k in WEIGHTS:
        vals = sorted(p[k] for p in pairs)
        report["components"][k] = {
            "weight": WEIGHTS[k],
            "min": round(vals[0], 4),
            "p50": round(vals[n // 2], 4),
            "max": round(vals[-1], 4),
            "frac_above_0.9": round(sum(v > 0.9 for v in vals) / n, 3),
            "frac_below_0.3": round(sum(v < 0.3 for v in vals) / n, 3),
        }
    return report


def _grade_size(a: int, b: int) -> str:
    """规模差距分级：只有真接近才说接近。"""
    if a <= 0 or b <= 0:
        return "规模不可比"
    lo, hi = min(a, b), max(a, b)
    ratio = hi / lo
    if ratio < 1.3:
        return f"代码规模接近（{a} vs {b} 个代码文件）"
    if ratio < 2.5:
        return f"代码规模同一量级（{a} vs {b} 个代码文件，约 {ratio:.1f} 倍）"
    if ratio < 8:
        return f"代码规模差距较大（{a} vs {b} 个代码文件，约 {ratio:.1f} 倍）"
    return f"代码规模差距很大（{a} vs {b} 个代码文件，约 {ratio:.0f} 倍）"


def _grade_primary(lang_a: str, lang_b: str) -> str:
    if lang_a == lang_b:
        return f"主语言同为 {lang_a}"
    return f"主语言不同（{lang_a} vs {lang_b}）"


def _grade_top_dirs(a: RepoFeatures, b: RepoFeatures, comp: dict) -> str | None:
    shared = sorted(a.top_level_dirs & b.top_level_dirs)
    if not shared:
        return None
    if comp["top_dirs"] >= 0.6:
        return f"顶层目录高度重合：{', '.join(shared[:5])}"
    return f"顶层目录部分重合：{', '.join(shared[:5])}"


def _grade_lang_shape(a: RepoFeatures, b: RepoFeatures, comp: dict) -> str | None:
    d = comp["lang_shape"]
    if d >= 0.9:
        return "语言集中程度接近"
    if d < 0.5:
        return "语言集中程度差异明显（一方单一语言、一方混合）"
    return None


def _grade_test(a: RepoFeatures, b: RepoFeatures, comp: dict) -> str | None:
    if comp["test_ratio"] >= 0.85:
        ra, rb = a.src_to_test_ratio, b.src_to_test_ratio
        return f"测试布局接近（源码:测试 ≈ {ra:.1f}:1 vs {rb:.1f}:1）"
    if comp["test_ratio"] < 0.5:
        return "测试布局差异明显"
    return None


def improved_explain(a: RepoFeatures, b: RepoFeatures, comp: dict, score: float) -> str:
    """按真实差距生成解释，且**只说确实为真的事**。

    与旧版的关键区别：规模这类量一律走分级文案，不再一律说「接近」。
    """
    from repo_structure_similarity import _top_lang

    reasons: list[str] = []
    reasons.append(_grade_primary(_top_lang(a), _top_lang(b)))
    reasons.append(_grade_size(a.n_code_files, b.n_code_files))

    for g in (
        _grade_top_dirs(a, b, comp),
        _grade_lang_shape(a, b, comp),
        _grade_test(a, b, comp),
    ):
        if g:
            reasons.append(g)

    if score >= 0.85:
        head = "高度相似"
    elif score >= 0.7:
        head = "较为相似"
    elif score >= 0.55:
        head = "中等相似"
    else:
        head = "相似度较低"
    return f"[{head}] " + "；".join(reasons)


def _self_test() -> int:
    ok = True
    print("[1] 规模分级文案：不再一律说「接近」")
    cases = [
        (1000, 1050, "接近"),
        (1170, 2000, "量级"),
        (1170, 3000, "差距较大"),
        (1170, 84, "差距很大"),
        (1170, 13000, "差距很大"),
    ]
    for a, b, expect in cases:
        txt = _grade_size(a, b)
        good = expect in txt
        print(f"  {'OK ' if good else 'FAIL'} {a:6d} vs {b:6d} -> {txt}")
        if not good:
            ok = False

    print("\n[2] 解释里不得出现与事实矛盾的措辞")
    A = RepoFeatures(name="A", path="", n_code_files=1170, n_test_files=659,
                     lang_counts={"Python": 1166}, top_level_dirs={"docs", "tests", "scripts"},
                     src_to_test_ratio=0.78)
    B = RepoFeatures(name="B", path="", n_code_files=84, n_test_files=39,
                     lang_counts={"Python": 84}, top_level_dirs={"docs", "tests", "scripts"},
                     src_to_test_ratio=1.15)
    s, comp = total_similarity(A, B)
    txt = improved_explain(A, B, comp, s)
    print(f"  解释：{txt}")
    good = "接近" not in txt.split("；")[1]        # 规模那一句不能是「接近」
    print(f"  {'OK ' if good else 'FAIL'} 1170 vs 84 不得描述为「接近」")
    ok = ok and good
    good2 = "差距" in txt
    print(f"  {'OK ' if good2 else 'FAIL'} 应明确说出差距")
    ok = ok and good2

    print("\n[3] 主语言不同必须说出来")
    C = RepoFeatures(name="C", path="", n_code_files=90, n_test_files=2,
                     lang_counts={"Go": 90}, top_level_dirs={"cmd", "internal"}, src_to_test_ratio=44)
    s2, comp2 = total_similarity(A, C)
    txt2 = improved_explain(A, C, comp2, s2)
    print(f"  解释：{txt2}")
    good3 = "主语言不同" in txt2
    print(f"  {'OK ' if good3 else 'FAIL'} Python vs Go 应判为不同")
    ok = ok and good3

    print("\n" + "=" * 46)
    print("全部通过。" if ok else "存在失败项。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_self_test())