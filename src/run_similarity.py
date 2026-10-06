"""
run_similarity.py — 在真实仓库语料上跑相似度矩阵，产出可写进 Writeup 的结果

用法:
    python run_similarity.py --corpus ..\\corpus --targets tiangolo/fastapi,psf/requests --out ..\\runs

【为什么分「目标」和「候选」】
  工具的用途是：给一个仓库，找结构上像它的**其他**仓库。
  所以目标仓库本身不出现在候选里（否则自相似恒为 1，没有信息量）。
  这一点会在 Writeup 里明确写出来——「我们刻意排除自匹配」本身是 Quality 的证据。

【中断与续跑】
  特征提取较慢（要遍历每个仓库的每个文件），所以特征单独缓存成 features.json。
  中断：Ctrl+C。续跑：重跑同一条命令，命中 features.json 缓存，只重算没算过的仓库。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from repo_structure_similarity import (  # noqa: E402
    RepoFeatures, WEIGHTS, extract_features, explain, total_similarity,
)


def load_features_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def build_features(corpus: Path, cache_path: Path, verbose: bool = True) -> dict[str, RepoFeatures]:
    cache = load_features_cache(cache_path)
    out: dict[str, RepoFeatures] = {}
    todo = 0

    for d in sorted(corpus.iterdir()):
        if not d.is_dir() or d.name == "state":
            continue
        slug = d.name.replace("__", "/")
        if slug in cache:
            f = RepoFeatures(
                name=slug, path=str(d),
                n_files=cache[slug].get("n_files", 0),
                n_code_files=cache[slug].get("n_code_files", 0),
                n_test_files=cache[slug].get("n_test_files", 0),
                n_dirs=cache[slug].get("n_dirs", 0),
                total_code_lines=cache[slug].get("total_code_lines", 0),
                max_depth=cache[slug].get("max_depth", 0),
                lang_counts=cache[slug].get("lang_counts", {}),
                top_level_dirs=set(cache[slug].get("top_level_dirs", [])),
                path_segments=cache[slug].get("path_segments", {}),
                test_path_ratio=cache[slug].get("test_path_ratio", 0.0),
                src_to_test_ratio=cache[slug].get("src_to_test_ratio", 0.0),
            )
            out[slug] = f
            continue

        todo += 1
        t0 = time.time()
        f = extract_features(d, name=slug)
        out[slug] = f
        cache[slug] = f.to_dict()
        if verbose:
            print(f"[feat] {slug:38s} 代码 {f.n_code_files:6d}  测试 {f.n_test_files:5d}  "
                  f"语言 {f.lang_counts}  {time.time()-t0:.1f}s")
        # 每算完一个就落盘，中断也不丢已算的
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    if verbose:
        print(f"[feat] 本次新算 {todo} 个，命中缓存 {len(out)-todo} 个")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--targets", required=True, help="逗号分隔的 owner/name")
    ap.add_argument("--out", required=True)
    ap.add_argument("--top", type=int, default=8)
    args = ap.parse_args()

    corpus = Path(args.corpus)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[sim] 提取特征（首次较慢，中断后重跑会命中缓存）...")
    feats = build_features(corpus, out_dir / "features.json")
    if not feats:
        print("!! 语料为空")
        return 2
    print(f"[sim] 语料共 {len(feats)} 个仓库\n")

    targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    results: dict = {}

    for tgt in targets:
        if tgt not in feats:
            print(f"!! 目标仓库不在语料中：{tgt}")
            continue
        tf = feats[tgt]
        rows = []
        for slug, f in feats.items():
            if slug == tgt:                       # 刻意排除自匹配
                continue
            score, comp = total_similarity(tf, f)
            rows.append((slug, score, comp))
        rows.sort(key=lambda r: (-r[1], r[0]))

        print("=" * 74)
        print(f"目标：{tgt}   （主语言 "
              f"{max(tf.lang_counts.items(), key=lambda kv: kv[1])[0] if tf.lang_counts else '?'}，"
              f"代码 {tf.n_code_files} 个文件，测试 {tf.n_test_files} 个）")
        print("=" * 74)
        shown = []
        for i, (slug, score, comp) in enumerate(rows[:args.top], start=1):
            print(f"{i:2d}. {slug:38s} {score:.4f}   {explain(tf, feats[slug], comp)}")
            shown.append({
                "rank": i, "repo": slug, "score": round(score, 6),
                "components": {k: round(v, 4) for k, v in comp.items()},
                "why": explain(tf, feats[slug], comp),
            })
        results[tgt] = {"target_features": tf.to_dict(), "top": shown}

    (out_dir / "similarity_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    # 全部目标之间的两两矩阵，便于展示整体结构
    print("\n" + "=" * 74)
    print("语料两两相似度矩阵（仅显示结构特征加权总分）")
    print("=" * 74)
    slugs = sorted(feats)
    short = {s: s.split("/")[-1][:12] for s in slugs}
    print(f"{'':14s}" + "".join(f"{short[s]:>13s}" for s in slugs))
    for a in slugs:
        line = f"{short[a]:14s}"
        for b in slugs:
            line += f"{1.0 if a == b else total_similarity(feats[a], feats[b])[0]:13.3f}"
        print(line)

    print(f"\n结果已写入 {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())