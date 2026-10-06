"""排查 fig2 与 lang_crosscheck.py 数字不一致的原因。

怀疑点：两者用的权重不同
  lang_crosscheck.py 用 total_similarity_v3() 的默认权重 WEIGHTS_V3_STRUCT
  但 —— 它是在 v3 权重加入之前写的！

时间线：
  - lang_crosscheck.py 在第 7 轮跑出 Python 1.00（当时只有 WEIGHTS_V2）
  - 第 7 轮之后才新增 WEIGHTS_V3_STRUCT（primary_lang 0.15 -> 0.04）
  - 第 9 轮 make_figures 用 total_similarity_v3() 默认走 v3

所以两者测的是**不同权重**下的结果，不是同一实验。
必须确认这一点，而不是任选其一。
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from similarity_v2 import WEIGHTS_V2, WEIGHTS_V3_STRUCT, RepoFeatures, \
    similarity_components_v2, total_similarity_v3  # noqa: E402

TOP_K = 5


def load():
    data = json.loads((Path("..") / "runs" / "balanced" / "features.json")
                      .read_text(encoding="utf-8-sig"))
    return {s: RepoFeatures(
        name=s, path="", n_files=d["n_files"], n_code_files=d["n_code_files"],
        n_test_files=d["n_test_files"], total_code_lines=d["total_code_lines"],
        max_depth=d.get("max_depth", 0), lang_counts=d["lang_counts"],
        top_level_dirs=set(d["top_level_dirs"]),
        src_to_test_ratio=d["src_to_test_ratio"]) for s, d in data.items()}


feats = load()
slugs = sorted(feats)
lang = {s: max(feats[s].lang_counts.items(), key=lambda kv: kv[1])[0]
        if feats[s].lang_counts else "?" for s in slugs}
dist = Counter(lang.values())
N = len(slugs)

print("=" * 72)
print("同一语料下，v2 权重 vs v3 权重的跨语言判别对比")
print("=" * 72)
print(f"{'lang':10s}{'n':>4s}{'随机期望':>10s}{'v2实测':>10s}{'v3实测':>10s}")
print("-" * 72)

results = {}
for L, cnt in dist.most_common():
    if cnt < 3:
        continue
    members = [s for s in slugs if lang[s] == L]
    exp = TOP_K * len(members) / N
    hits2, hits3 = [], []
    for q in members:
        r2 = [(s, sum(WEIGHTS_V2[k] * similarity_components_v2(feats[q], feats[s])[k]
                      for k in WEIGHTS_V2)) for s in slugs if s != q]
        r3 = [(s, total_similarity_v3(feats[q], feats[s])[0]) for s in slugs if s != q]
        r2.sort(key=lambda x: -x[1])
        r3.sort(key=lambda x: -x[1])
        hits2.append(sum(1 for s, _ in r2[:TOP_K] if lang[s] == L))
        hits3.append(sum(1 for s, _ in r3[:TOP_K] if lang[s] == L))
    a2 = sum(hits2) / len(hits2)
    a3 = sum(hits3) / len(hits3)
    results[L] = (len(members), exp, a2, a3)
    print(f"{L:10s}{len(members):>4d}{exp:>10.2f}{a2:>10.2f}{a3:>10.2f}")

print()
print("primary_lang 权重: v2 =", WEIGHTS_V2["primary_lang"],
      " v3 =", WEIGHTS_V3_STRUCT["primary_lang"])
print()
print("=" * 72)
print("判读")
print("=" * 72)
for L, (n, exp, a2, a3) in results.items():
    j2 = "有效" if a2 > exp * 1.25 else ("偏弱" if a2 > exp else "无效")
    j3 = "有效" if a3 > exp * 1.25 else ("偏弱" if a3 > exp else "无效")
    print(f"  {L:10s} v2: {a2:.2f} vs {exp:.2f} -> {j2:4s}   "
          f"v3: {a3:.2f} vs {exp:.2f} -> {j3}")
print()
print("结论：两者测的不是同一实验。文档里的 1.00 来自 v2 权重，")
print("      make_figures 画的 3.87 来自 v3 权重。")
print("      必须选定一个口径并让文档与图一致，否则就是自相矛盾。")
