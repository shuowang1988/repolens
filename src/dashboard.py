"""
dashboard.py — RepoLens 交互看板（单文件 HTML，离线可开）

对应主办方在 Best New Resource 里亲自举例的：
  「New software could be a dashboard to explore Github repos that are similar
    in structure to a target repo」
本模块就是把前几轮算出来的结果变成可看、可查的页面。

设计要点（都是被评分标准逼出来的）：
  - **可解释性优先**：每条结果不只给分，还给「为什么像」和 8 个分量的柱状图
  - **诚实展示边界**：顶部固定横幅写明「不做跨语言判别」与「无标注数据」两条限制
  - **离线自包含**：单 HTML 文件，内联 CSS/JS/数据，双击即可开，不联网

输入：runs/balanced/features.json（本轮 41 仓特征）
输出：runs/balanced/dashboard.html

【中断与续跑】本脚本无状态，通常几秒跑完。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from similarity_v2 import WEIGHTS_V3_STRUCT, RepoFeatures, explain_v2, \
    total_similarity_v3  # noqa: E402

TOP_N = 12


def load(cache: Path) -> dict[str, RepoFeatures]:
    data = json.loads(cache.read_text(encoding="utf-8-sig"))
    out = {}
    for s, d in data.items():
        out[s] = RepoFeatures(
            name=s, path="", n_files=d["n_files"], n_code_files=d["n_code_files"],
            n_test_files=d["n_test_files"], total_code_lines=d["total_code_lines"],
            max_depth=d.get("max_depth", 0), lang_counts=d["lang_counts"],
            top_level_dirs=set(d["top_level_dirs"]),
            src_to_test_ratio=d["src_to_test_ratio"])
    return out


COMP_LABEL = {
    "size": "code size",
    "primary_lang": "primary language",
    "lang_shape": "language mix",
    "top_dir_count": "hierarchy width",
    "flat_single_pkg": "layout type",
    "top_dirs": "top-level dirs",
    "depth": "directory depth",
    "test_ratio": "test layout",
}


def build(feats: dict[str, RepoFeatures]) -> dict:
    slugs = sorted(feats)
    repos = []
    for s in slugs:
        f = feats[s]
        lang = max(f.lang_counts.items(), key=lambda kv: kv[1])[0] if f.lang_counts else "?"
        repos.append({
            "id": s,
            "lang": lang,
            "code": f.n_code_files,
            "test": f.n_test_files,
            "depth": f.max_depth,
            "topdirs": sorted(f.top_level_dirs),
            "ratio": round(f.src_to_test_ratio, 2),
        })

    sim: dict[str, list] = {}
    for q in slugs:
        rows = []
        for s in slugs:
            if s == q:
                continue
            score, comp = total_similarity_v3(feats[q], feats[s])
            rows.append({
                "id": s,
                "score": round(score, 4),
                "why": explain_v2(feats[q], feats[s], comp, score),
                "comp": {k: round(comp[k], 3) for k in WEIGHTS_V3_STRUCT},
            })
        rows.sort(key=lambda r: (-r["score"], r["id"]))
        sim[q] = rows[:TOP_N]
    return {"repos": repos, "sim": sim,
            "weights": WEIGHTS_V3_STRUCT, "comp_label": COMP_LABEL}


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RepoLens - structural repository similarity</title>
<style>
  :root{
    --bg:#0f1115; --panel:#171a21; --line:#262b36; --fg:#e6e9ef;
    --dim:#9aa4b2; --accent:#4c9aff; --warn:#e0a458; --ok:#5ac18e;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",
       "PingFang SC","Microsoft YaHei",sans-serif}
  header{padding:20px 24px 12px;border-bottom:1px solid var(--line)}
  h1{margin:0 0 4px;font-size:20px;letter-spacing:.3px}
  .sub{color:var(--dim);font-size:13px}
  .notice{margin:14px 24px;padding:12px 14px;border-left:3px solid var(--warn);
          background:rgba(224,164,88,.08);border-radius:0 6px 6px 0;font-size:13px}
  .notice b{color:var(--warn)}
  .layout{display:grid;grid-template-columns:290px 1fr;gap:0;min-height:calc(100vh - 150px)}
  aside{border-right:1px solid var(--line);overflow-y:auto;max-height:calc(100vh - 150px)}
  .search{padding:12px 14px;border-bottom:1px solid var(--line);position:sticky;top:0;
          background:var(--bg)}
  .search input{width:100%;padding:7px 10px;border-radius:6px;border:1px solid var(--line);
                background:var(--panel);color:var(--fg);font-size:13px}
  .repolist{padding:6px 0}
  .repoitem{padding:8px 14px;cursor:pointer;border-left:2px solid transparent}
  .repoitem:hover{background:var(--panel)}
  .repoitem.on{background:var(--panel);border-left-color:var(--accent)}
  .repoitem .n{font-size:13px;word-break:break-all}
  .repoitem .m{font-size:11px;color:var(--dim);margin-top:2px}
  main{padding:18px 24px;overflow-y:auto;max-height:calc(100vh - 150px)}
  .tgt{margin-bottom:16px}
  .tgt h2{margin:0 0 6px;font-size:17px}
  .meta{color:var(--dim);font-size:12px}
  table{width:100%;border-collapse:collapse}
  th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
  th{font-size:12px;color:var(--dim);font-weight:600;text-transform:uppercase;
     letter-spacing:.4px;position:sticky;top:0;background:var(--bg)}
  tr:hover td{background:var(--panel)}
  .score{font-variant-numeric:tabular-nums;font-weight:600;color:var(--accent);white-space:nowrap}
  .why{font-size:12px;color:var(--dim);margin-top:4px;line-height:1.5}
  .bars{display:flex;gap:2px;margin-top:6px;height:16px;align-items:flex-end}
  .bar{flex:1;background:var(--line);position:relative;border-radius:1px}
  .bar>span{position:absolute;bottom:0;left:0;right:0;background:var(--accent);
            border-radius:1px;display:block}
  .bar.on>span{background:var(--ok)}
  .legend{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px;font-size:11px;color:var(--dim)}
  .legend i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px}
  .empty{color:var(--dim);padding:40px 0;text-align:center}
  code{background:var(--panel);padding:1px 5px;border-radius:3px;font-size:12px}
</style>
</head>
<body>
<header>
  <h1>RepoLens &mdash; structural repository similarity</h1>
  <div class="sub" id="hsub"></div>
</header>

<div class="notice">
  <b>Method boundaries (read first)</b><br>
  1) Weights are <b>not supervised</b>. This project has <b>no labelled dataset</b>; the
     weights come from unsupervised diagnostics and explicit design trade-offs, and should
     not be read as an optimum.<br>
  2) Language discrimination is an <b>emergent behaviour, not a designed guarantee</b>.
     Language is one of eight components; measured cross-language separation comes from the
     weighted combination and exceeds random expectation on this corpus, but that is not
     claimed to hold on arbitrary corpora.<br>
  3) Structure and content are <b>complementary, not substitutes</b>. Mean Top-5 overlap is
     only __OVERLAP__, so the two signals are close to orthogonal and should be used
     together.<br>
  4) Historical defect on record: the v1 <b>size</b> component <b>could never reach zero</b>
     (measured floor __V1MIN__), so a __SPAN__x size difference still earned about a third of
     the credit. The current piecewise-linear form can award zero.
</div>

<div class="layout">
  <aside>
    <div class="search"><input id="q" placeholder="Search repositories..."></div>
    <div class="repolist" id="list"></div>
  </aside>
  <main id="main"><div class="empty">Select a repository on the left</div></main>
</div>

<script>
const DATA = __DATA__;
const CL = DATA.comp_label;
const W = DATA.weights;
const meta = Object.fromEntries(DATA.repos.map(r => [r.id, r]));
let cur = null;

document.getElementById('hsub').textContent =
  DATA.repos.length + ' repositories · 8 interpretable components · Top-' + DATA.sim[Object.keys(DATA.sim)[0]].length;

function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}

function renderList(filter){
  const el = document.getElementById('list');
  const f = (filter||'').toLowerCase();
  const items = DATA.repos.filter(r=>!f || r.id.toLowerCase().includes(f));
  el.innerHTML = items.map(r=>{
    const on = r.id===cur ? ' on' : '';
    return `<div class="repoitem${on}" data-id="${esc(r.id)}">
      <div class="n">${esc(r.id)}</div>
      <div class="m">${esc(r.lang)} · ${r.code} files · depth ${r.depth}</div>
    </div>`;
  }).join('');
  el.querySelectorAll('.repoitem').forEach(n=>{
    n.onclick=()=>{cur=n.dataset.id;renderList(document.getElementById('q').value);renderMain()};
  });
}

function bars(c){
  return '<div class="bars">'+Object.keys(W).map(k=>{
    const v = c[k]==null?0:c[k];
    const h = Math.max(2, Math.round(v*16));
    const strong = v>=0.5?' on':'';
    return `<div class="bar${strong}" title="${esc(CL[k]||k)}: ${v}"><span style="height:${h}px"></span></div>`;
  }).join('')+'</div>';
}

function renderMain(){
  const m = document.getElementById('main');
  if(!cur){m.innerHTML='<div class="empty">Select a repository on the left</div>';return}
  const t = meta[cur];
  const rows = DATA.sim[cur]||[];
  m.innerHTML = `
    <div class="tgt">
      <h2>${esc(cur)}</h2>
      <div class="meta">
        ${esc(t.lang)} · ${t.code} code files · ${t.test} test files ·
        max depth ${t.depth} · source:test ${t.ratio}:1<br>
        top-level directories: ${t.topdirs.map(d=>'<code>'+esc(d)+'</code>').join(' ')}
      </div>
      <div class="legend">${Object.keys(W).map(k=>
        `<span><i style="background:${W[k]>=0.15?'var(--ok)':'var(--line)'}"></i>${esc(CL[k]||k)} ${W[k]}</span>`
      ).join('')}</div>
    </div>
    <table>
      <thead><tr>
        <th style="width:34%">Repository</th><th style="width:70px">Score</th>
        <th>Components / why it matched</th>
      </tr></thead>
      <tbody>
      ${rows.map(r=>{
        const s = meta[r.id];
        return `<tr>
          <td>
            <div><a href="#" style="color:var(--fg);text-decoration:none"
                 onclick="cur='${esc(r.id)}';renderList(document.getElementById('q').value);renderMain();return false">${esc(r.id)}</a></div>
            <div class="m" style="color:var(--dim);font-size:11px;margin-top:2px">
              ${esc(s.lang)} · ${s.code} files · depth ${s.depth}</div>
          </td>
          <td class="score">${r.score.toFixed(4)}</td>
          <td>
            ${bars(r.comp)}
            <div class="why">${esc(r.why)}</div>
          </td>
        </tr>`}).join('')}
      </tbody>
    </table>`;
}

document.getElementById('q').addEventListener('input',e=>renderList(e.target.value));
renderList('');
cur = DATA.repos[0] ? DATA.repos[0].id : null;
renderList(''); renderMain();
</script>
</body>
</html>
"""


def notice_numbers() -> dict:
    """横幅里的数字必须来自重算产物，不得硬编码。

    起因（2026-10-05）：横幅里一直写着 0.278（旧 v2 权重下的重叠值），
    而图与文档早已是 0.371 —— 交付物在自相矛盾，检查器却全过。
    现在改为从 runs/balanced/derived_truth.json 读取，缺了就直接报错，
    绝不用一个"看起来对"的默认值糊过去。
    """
    tf = Path("..") / "runs" / "balanced" / "derived_truth.json"
    if not tf.exists():
        raise SystemExit(
            f"!! 缺少 {tf.resolve()}\n"
            "   横幅里的重叠值 / 规模下限 / 规模跨度都必须从重算产物读取。\n"
            "   请先运行：python derive_truth.py")
    t = json.loads(tf.read_text(encoding="utf-8"))
    try:
        return {
            "overlap": f"{t['overlap']['overlap']['struct|content']:.3f}",
            "v1_min": f"{t['core']['size_component']['v1_min']:.3f}",
            "span": f"{t['core']['size_span_ratio']:.0f}",
        }
    except KeyError as e:
        raise SystemExit(f"!! {tf.resolve()} 缺少字段 {e}，请重跑 derive_truth.py")


def main() -> int:
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("..") / "runs" / "balanced"
    cache = base / "features.json"
    if not cache.exists():
        print(f"!! 找不到 {cache}")
        print("请先跑 run_similarity.py 生成特征缓存。")
        return 2

    feats = load(cache)
    print(f"载入 {len(feats)} 个仓库特征")
    data = build(feats)
    print(f"计算相似度矩阵：{len(feats)} x {len(feats)-1} ...", end="", flush=True)
    # build() 已算完，这里只是确认
    print(" 完成")

    nums = notice_numbers()
    html = HTML.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    for token, val in (("__OVERLAP__", nums["overlap"]),
                       ("__V1MIN__", nums["v1_min"]),
                       ("__SPAN__", nums["span"])):
        html = html.replace(token, val)
    for token in ("__OVERLAP__", "__V1MIN__", "__SPAN__", "__DATA__"):
        if token in html:
            raise SystemExit(f"!! 占位符 {token} 未被替换")
    out = base / "dashboard.html"
    out.write_text(html, encoding="utf-8")

    size_kb = out.stat().st_size / 1024
    print(f"\n已生成 {out}  ({size_kb:.0f} KB, 自包含离线)")
    print(f"  仓库数      : {len(data['repos'])}")
    print(f"  每个仓库 Top: {len(data['sim'][data['repos'][0]['id']])}")
    print(f"  分量        : {len(data['weights'])}")
    print("\n打开方式：直接双击该 HTML 文件（不需要联网、不需要服务器）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
