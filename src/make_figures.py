"""
make_figures.py — 生成 Writeup 配图（全部来自实测数据，无手工编造）

Clarity 是五项评分维度之一。这里只画四张真正承载论证的图，不堆砌：

  Fig 1  Method overlap   —— 结构 vs 内容 / 文件名 的 Top-5 重叠矩阵（核心主张）
  Fig 2  Language         —— 实测 vs 随机期望（跨语言命中率）
  Fig 3  Components       —— 8 个分量的取值分布（质量证据）
  Fig 4  v1 vs v2 size    —— 修正前后的 size 分量分布（方法演进）

⚠️ 两条被真实踩过的坑，改动本文件时必须守住：
  1. 图上的每一个数字都由数据算出，不得写死。曾把旧值 0.278 硬编码进 Fig 1 标注，
     改权重后重算了矩阵却没改标注，图上「数值 0.371 但箭头写 0.278」。
  2. **图的标题也是结论，也必须由数据算出。** Fig 2 曾长期写死
     「实测低于随机期望」，而那个结论源于 lang_crosscheck.py 的算术 bug；
     bug 修好后条形图变成 4.80 vs 1.83（远高于期望），标题却还在说"低于"，
     而且 ylim 按 max(期望)*1.35 夹住，柱子直接被截断。
     交付物自相矛盾而检查器全过 —— 现在标题改为按实测判定。

图注为英文：正文是英文，评委是 Google DeepMind 研究员。

【中断与续跑】每张图独立产出，已存在则跳过（加 --force 可重画）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from repo_structure_similarity import RepoFeatures as F1, total_similarity  # noqa: E402
from similarity_v2 import WEIGHTS_V3_STRUCT, RepoFeatures, similarity_components_v2, \
    total_similarity_v3  # noqa: E402

plt.rcParams["font.sans-serif"] = ["Segoe UI", "Arial", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 160

BG = "#0f1115"
FG = "#e6e9ef"
DIM = "#9aa4b2"
ACC = "#4c9aff"
OK = "#5ac18e"
WARN = "#e0a458"
GRID = "#262b36"

FEATURES = Path("..") / "runs" / "balanced" / "features.json"
CORPUS = Path("..") / "corpus"


def style(ax, title, sub=""):
    ax.set_facecolor(BG)
    ax.figure.set_facecolor(BG)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.tick_params(colors=DIM, labelsize=9)
    ax.xaxis.label.set_color(DIM)
    ax.yaxis.label.set_color(DIM)
    ax.set_title(title, color=FG, fontsize=12, pad=14 if sub else 8, loc="left")
    if sub:
        ax.text(0, 1.02, sub, transform=ax.transAxes, color=DIM, fontsize=9)
    ax.grid(axis="y", color=GRID, lw=0.6, alpha=0.7)
    ax.set_axisbelow(True)


def load(cache: Path = FEATURES) -> dict[str, RepoFeatures]:
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


def _slugs() -> list[str]:
    return sorted(load())


# ------------------------------------------------------------------ Fig 1
def fig_overlap(out: Path, TOP_K=5) -> Path:
    """结构 / 内容 / 文件名 三者的 Top-K 重叠矩阵"""
    slugs = _slugs()
    feats = load()

    def readme(slug):
        d = CORPUS / slug.replace("/", "__")
        for n in ("README.md", "README.rst", "README.txt", "README"):
            p = d / n
            if p.exists() and p.stat().st_size > 0:
                try:
                    return p.read_text(encoding="utf-8", errors="ignore")[:20000]
                except OSError:
                    return ""
        return ""

    docs, keep = [], []
    for s in slugs:
        t = readme(s)
        if len(t) >= 200:
            docs.append(t)
            keep.append(s)

    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    M = TfidfVectorizer(stop_words="english", max_features=20000,
                        sublinear_tf=True, min_df=2).fit_transform(docs)
    C = cosine_similarity(M)
    idx = {s: i for i, s in enumerate(keep)}

    import re
    from collections import Counter

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

    def jac(a, b):
        A, B = fns[a], fns[b]
        return len(A & B) / len(A | B) if A and B else 0.0

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
        r = [(s, jac(q, s)) for s in slugs if s != q]
        r.sort(key=lambda x: -x[1])
        return [s for s, _ in r[:TOP_K]]

    R = {n: {} for n in ("struct", "content", "fn")}
    for q in slugs:
        R["struct"][q] = set(rank_struct(q))
        R["content"][q] = set(rank_content(q))
        R["fn"][q] = set(rank_fn(q))

    names = {"struct": "Structural\n(RepoLens)", "content": "README TF-IDF",
             "fn": "Filename Jaccard"}
    keys = ["struct", "content", "fn"]
    mat = np.zeros((3, 3))
    for i, a in enumerate(keys):
        for j, b in enumerate(keys):
            vals = []
            for q in slugs:
                ca, cb = R[a].get(q, set()), R[b].get(q, set())
                if not ca or not cb:
                    continue
                vals.append(len(ca & cb) / TOP_K)
            mat[i, j] = np.mean(vals) if vals else 0

    fig, ax = plt.subplots(figsize=(5.6, 4.6))
    style(ax, f"Top-{TOP_K} overlap between similarity notions",
          f"{len(slugs)} repositories · lower = the two notions disagree more")
    im = ax.imshow(mat, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(3))
    ax.set_yticks(range(3))
    ax.set_xticklabels([names[k] for k in keys], fontsize=8)
    ax.set_yticklabels([names[k] for k in keys], fontsize=8)
    ax.tick_params(colors=DIM)
    for i in range(3):
        for j in range(3):
            v = mat[i, j]
            ax.text(j, i, f"{v:.3f}", ha="center", va="center",
                    color=BG if v > 0.55 else FG,
                    fontsize=12 if i == j else 13,
                    fontweight="bold" if i != j else "normal")
    ax.grid(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.ax.tick_params(colors=DIM, labelsize=8)
    cb.outline.set_edgecolor(GRID)
    # ⚠️ 标注必须用算出来的值，不能写死字符串。
    #    曾因调整权重后只重算了矩阵、标注仍写死旧值 0.278，
    #    图上出现「数值 0.371 但箭头写 0.278」的自相矛盾。
    key = mat[0, 1]
    ax.annotate(f"{key:.3f}", xy=(0.5, 1.0), xytext=(0.5, 1.75),
                color=WARN, fontsize=11, ha="center",
                arrowprops=dict(arrowstyle="->", color=WARN))
    fig.tight_layout()
    p = out / "fig1_overlap.png"
    fig.savefig(p, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    return p


# ------------------------------------------------------------------ Fig 2
def fig_lang(out: Path, TOP_K=5) -> Path:
    """跨语言判别：实测 vs 随机期望"""
    feats = load()
    slugs = sorted(feats)
    lang = {s: max(feats[s].lang_counts.items(), key=lambda kv: kv[1])[0]
            if feats[s].lang_counts else "?" for s in slugs}
    from collections import Counter
    dist = Counter(lang.values())
    N = len(slugs)

    rows = []
    for L, cnt in dist.most_common():
        if cnt < 3:
            continue
        members = [s for s in slugs if lang[s] == L]
        exp = TOP_K * len(members) / N
        hits = []
        for q in members:
            r = [(s, total_similarity_v3(feats[q], feats[s])[0])
                 for s in slugs if s != q]
            r.sort(key=lambda x: -x[1])
            top = [s for s, _ in r[:TOP_K]]
            hits.append(sum(1 for s in top if lang[s] == L))
        rows.append((L, len(members), exp, np.mean(hits) if hits else 0))

    exp = [r[2] for r in rows]
    act = [r[3] for r in rows]

    # ⚠️ 标题是一个结论，必须由数据判定，不能写死。
    above = sum(1 for e, a in zip(exp, act) if a > e)
    verdict = ("measured above random expectation for every class"
               if above == len(rows) else
               f"above random expectation for {above}/{len(rows)} classes")

    fig, ax = plt.subplots(figsize=(6.4, 3.9))
    style(ax, f"Same-language neighbours in Top-{TOP_K}: {verdict}",
          f"Top-{TOP_K} overlap vs random expectation · {N} repositories, "
          f"language-balanced corpus")
    xs = np.arange(len(rows))
    w = 0.36
    ax.bar(xs - w/2, exp, w, label="random expectation", color=GRID,
           edgecolor=DIM, lw=0.6)
    ax.bar(xs + w/2, act, w, label="measured", color=ACC, edgecolor="none")
    for i, (e, a) in enumerate(zip(exp, act)):
        ax.text(i + w/2, a + 0.06, f"{a:.2f}", ha="center",
                color=ACC if a >= e else WARN, fontsize=9, fontweight="bold")
        ax.text(i - w/2, e + 0.06, f"{e:.2f}", ha="center", color=DIM, fontsize=8)
    ax.set_xticks(xs)
    ax.set_xticklabels([f"{r[0]}\n(n={r[1]})" for r in rows], fontsize=9)
    ax.set_ylabel(f"same-language repos in Top-{TOP_K} (mean)")
    leg = ax.legend(facecolor=BG, edgecolor=GRID, fontsize=9, loc="upper right")
    for t in leg.get_texts():
        t.set_color(FG)
    # ⚠️ 曾经按 max(期望)*1.35 设上限，把"实测"的高柱直接截断 —— 上限必须同时考虑两组数据
    ax.set_ylim(0, max(max(exp), max(act)) * 1.22)
    fig.tight_layout()
    p = out / "fig2_language.png"
    fig.savefig(p, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    return p


# ------------------------------------------------------------------ Fig 3
def fig_components(out: Path) -> Path:
    """8 个分量在全部两两组合上的取值分布"""
    feats = load()
    slugs = sorted(feats)
    from collections import defaultdict
    vals = defaultdict(list)
    for i, a in enumerate(slugs):
        for b in slugs[i + 1:]:
            comp = similarity_components_v2(feats[a], feats[b])
            for k, v in comp.items():
                vals[k].append(v)

    keys = list(WEIGHTS_V3_STRUCT)

    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    style(ax, "Distribution of each similarity component",
          f"{len(slugs)*(len(slugs)-1)//2} repository pairs · "
          f"a wide, high box means the component separates poorly")
    data = [vals[k] for k in keys]
    bp = ax.boxplot(data, vert=False, patch_artist=True, widths=0.6,
                    medianprops=dict(color=FG, lw=1.4),
                    flierprops=dict(marker=".", markersize=2,
                                    markerfacecolor=GRID, markeredgecolor="none"))
    for patch, k in zip(bp["boxes"], keys):
        w = WEIGHTS_V3_STRUCT[k]
        patch.set_facecolor(ACC if w >= 0.15 else GRID)
        patch.set_alpha(0.85 if w >= 0.15 else 0.9)
        patch.set_edgecolor(ACC if w >= 0.15 else DIM)
        patch.set_lw(1.2)
    ax.set_yticklabels([f"{k}  (w={WEIGHTS_V3_STRUCT[k]})" for k in keys],
                       fontsize=9)
    ax.set_xlabel("component value")
    ax.grid(axis="x", color=GRID, lw=0.6, alpha=0.7)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(-0.02, 1.02)
    fig.tight_layout()
    p = out / "fig3_components.png"
    fig.savefig(p, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    return p


# ------------------------------------------------------------------ Fig 4
def fig_size_fix(out: Path) -> Path:
    """v1 与 v2 的 size 分量分布对比"""
    feats = load()
    slugs = sorted(feats)
    v1, v2 = [], []
    for i, a in enumerate(slugs):
        fa = F1(name=a, path="", n_code_files=feats[a].n_code_files,
                lang_counts=feats[a].lang_counts)
        for b in slugs[i + 1:]:
            fb = F1(name=b, path="", n_code_files=feats[b].n_code_files,
                    lang_counts=feats[b].lang_counts)
            v1.append(total_similarity(fa, fb)[1]["size"])
            v2.append(similarity_components_v2(feats[a], feats[b])["size"])

    fig, ax = plt.subplots(figsize=(6.6, 3.6))
    # 标题里的倍数也必须从数据算，不能写死旧语料的 "155 倍"
    spans = sorted(feats[s].n_code_files for s in slugs)
    ratio = spans[-1] / max(1, spans[0])
    style(ax, "The size component, before and after",
          f"v1 (log-smoothed) never reaches zero even across a {ratio:.0f}x "
          f"size span; v2 (piecewise-linear) can")
    bins = np.linspace(0, 1, 41)
    ax.hist(v1, bins=bins, color=WARN, alpha=0.55, label=f"v1 (min={min(v1):.3f})")
    ax.hist(v2, bins=bins, color=OK, alpha=0.55, label=f"v2 (min={min(v2):.3f})")
    ax.axvline(min(v1), color=WARN, ls="--", lw=1.2)
    ax.set_xlabel("size component value")
    ax.set_ylabel("repository pairs")
    # 数值全部由实测得出，标题/标注不得写死旧语料的数字
    ax.text(min(v1), ax.get_ylim()[1] * 0.92,
            f" v1 floors at {min(v1):.3f} —\n it can never award zero",
            color=WARN, fontsize=9, va="top")
    leg = ax.legend(facecolor=BG, edgecolor=GRID, fontsize=9)
    for t in leg.get_texts():
        t.set_color(FG)
    fig.tight_layout()
    p = out / "fig4_size_fix.png"
    fig.savefig(p, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../runs/figures")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    jobs = [("Fig1 method overlap", "fig1_overlap.png", fig_overlap),
            ("Fig2 language", "fig2_language.png", fig_lang),
            ("Fig3 components", "fig3_components.png", fig_components),
            ("Fig4 size fix", "fig4_size_fix.png", fig_size_fix)]
    for name, fname, fn in jobs:
        p = out / fname
        if p.exists() and not args.force:
            print(f"[skip] {name} -> {p.name} (已存在, --force 可重画)")
            continue
        try:
            got = fn(out)
            print(f"[ok  ] {name} -> {got.name}  {got.stat().st_size/1024:.0f} KB")
        except Exception as e:
            print(f"[FAIL] {name}: {type(e).__name__}: {e}")
            return 1
    print(f"\n输出目录: {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
