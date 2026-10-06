"""
lang_crosscheck.py — 均衡语料上重测「跨语言判别」，验证上一轮的负面结论

上一轮（19 仓，Python 16 / Go 2 / Rust 1 / JS 0）实测：
  gin(Go) 的 Top-5 里 Python 占 4 席，最佳 Go 候选 0.5644 反而低于
  最佳 Python 候选 0.5501 ... 结论是「纯结构无法跨语言判别」。

但那个语料严重不平衡，结论可能是**类目数量优势**造成的假象。
本轮均衡到 41 仓（Python 16 / Rust 9 / Go 7 / Java 4 / JS 3）后重测。

判定标准（事先定好，避免事后找理由）：
  对每个主语言 L，取 L 的所有仓库作为查询，每个查询的 Top-5 中
  同语言（L）的占比。若显著高于随机期望，则跨语言判别成立。
  随机期望 = L 的仓库数 / 总仓库数。
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from similarity_v2 import WEIGHTS_V2, RepoFeatures, similarity_components_v2, \
    total_similarity_v2  # noqa: E402
from repo_structure_similarity import RepoFeatures as F1, total_similarity  # noqa: E402

TOP_K = 5


def load(cache: Path) -> dict[str, RepoFeatures]:
    data = __import__("json").loads(cache.read_text(encoding="utf-8-sig"))
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


feats = load(Path("..") / "runs" / "balanced" / "features.json")
slugs = sorted(feats)

lang_of = {s: max(feats[s].lang_counts.items(), key=lambda kv: kv[1])[0]
           if feats[s].lang_counts else "?" for s in slugs}
dist = Counter(lang_of.values())
N = len(slugs)

print("=" * 80)
print(f"balanced corpus: {N} repos")
print("=" * 80)
for l, c in dist.most_common():
    print(f"  {l:10s} {c:3d}  随机期望 Top-{TOP_K} 命中率 = {TOP_K*c/N:.2f}")
print()

# ---- per-language hit rate ----
print("=" * 80)
print(f"per-query: Top-{TOP_K} 中同语言占比（v2 / v1 各算一遍）")
print("=" * 80)
print(f"{'lang':10s}{'n':>4s}{'期望':>8s}{'v2实测':>10s}{'v1实测':>10s}{'v2判定':>12s}")
print("-" * 80)

rows = []
for lang in [l for l, c in dist.most_common() if c >= 3]:
    members = [s for s in slugs if lang_of[s] == lang]
    exp = TOP_K * len(members) / N

    hits_v2 = []
    hits_v1 = []
    for q in members:
        rows_v2 = []
        for s in slugs:
            if s == q:
                continue
            sc, _ = total_similarity_v2(feats[q], feats[s])
            rows_v2.append((s, sc))
        rows_v2.sort(key=lambda r: -r[1])
        top = [s for s, _ in rows_v2[:TOP_K]]
        hits_v2.append(sum(1 for s in top if lang_of[s] == lang))

        fq1 = F1(name=q, path="", n_code_files=feats[q].n_code_files,
                 lang_counts=feats[q].lang_counts)
        rows_v1 = []
        for s in slugs:
            if s == q:
                continue
            f1 = F1(name=s, path="", n_code_files=feats[s].n_code_files,
                    lang_counts=feats[s].lang_counts)
            sc, _ = total_similarity(fq1, f1)
            rows_v1.append((s, sc))
        rows_v1.sort(key=lambda r: -r[1])
        top1 = [s for s, _ in rows_v1[:TOP_K]]
        hits_v1.append(sum(1 for s in top1 if lang_of[s] == lang))

    # ⚠️ 曾在这里有一个算术 bug：hits_v2 是「命中个数」而非「比率」，
    #    却又除了一次 len(members)*TOP_K，等于把结果缩小了 TOP_K 倍。
    #    这导致 Writeup 与实验文档里一度出现「Python 1.00 < 随机期望 1.83」
    #    的错误结论，进而误判为「跨语言判别失效」。
    #    正确口径：平均每个查询的 Top-5 中有几个同语言（期望 0~TOP_K）。
    r2 = sum(hits_v2) / len(members)
    r1 = sum(hits_v1) / len(members)
    verdict = "有效" if r2 > exp * 1.25 else ("偏弱" if r2 > exp else "无效")
    rows.append((lang, len(members), exp, r2, r1, verdict))
    print(f"{lang:10s}{len(members):>4d}{exp:>8.2f}{r2:>10.2f}{r1:>10.2f}{verdict:>12s}")

print()
eff = [r for r in rows if r[5] == "无效"]
print("=" * 80)
if not eff:
    print("结论：语言均衡后，v2 对所有语言的跨语言判别都有效。")
    print("上一轮 19 仓时的负面结论，应归因于【类目不平衡】，而非方法本身。")
else:
    print("仍无效的语言：" + ", ".join(f"{r[0]}({r[3]:.2f}<{r[2]:.2f})" for r in eff))
    print("=> 纯结构相似度对这些语言确实无判别力。")
print("=" * 80)
