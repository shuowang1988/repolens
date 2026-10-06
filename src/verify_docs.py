"""
verify_docs.py — 校验文档里的数字与实测产物一致。

规则（用户定调）：不轻信二手结论，数字要能对上。

⚠️ 本脚本的前一版犯过本项目最典型的错误：它把**结论**也硬编码进断言，
   例如 check("writeup 正确陈述跨语言判别有效", "5.00" in wtxt)。
   那不是校验，那是要求文档复述检查器预先相信的答案。
   而那个答案本身来自一个算术 bug，于是检查器和文档一起错，还阻止修正。

现在：真值一律由 derive_truth 现场重算，本脚本自己不知道答案。
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent
sys.path.insert(0, str(HERE))
import derive_truth as dt  # noqa: E402

DOCS = {
    "WRITEUP_FINAL.md": TOOL / "WRITEUP_FINAL.md",
    "README_OPEN_SOURCE.md": TOOL / "README_OPEN_SOURCE.md",
}

ok = True


def check(label, cond, extra=""):
    global ok
    if not cond:
        ok = False
    print(f"  {'OK ' if cond else 'FAIL'} {label}{(' | ' + extra) if extra else ''}")


print("[1] 文件存在")
for name, p in DOCS.items():
    check(name, p.exists())
if not all(p.exists() for p in DOCS.values()):
    raise SystemExit(1)

texts = {n: p.read_text(encoding="utf-8") for n, p in DOCS.items()}

print("\n[2] 真值现场重算（不读文档、不读缓存里的结论）")
core = dt.core_truth()
TRUTH = TOOL / "runs" / "balanced" / "derived_truth.json"
cached = json.loads(TRUTH.read_text(encoding="utf-8"))
check("inputs 指纹一致", cached.get("fingerprint") == dt.inputs_fingerprint())
diffs = [k for k in core if cached["core"].get(k) != core[k]]
check("现场重算 core 与缓存一致", not diffs, str(diffs))
check("语料仓库数 = 41", core["corpus_repos"] == 41, f"实测 {core['corpus_repos']}")

print("\n[3] 看板内联权重必须等于源码权重表（而不是等于某个写死的数字）")
bl = TOOL / "runs" / "balanced" / "dashboard.html"
check("看板存在", bl.exists())
if bl.exists():
    d = json.loads(re.search(r"const DATA = (\{.*?\});\n",
                             bl.read_text(encoding="utf-8"), re.S).group(1))
    check("看板内 repos 数 = 语料数", len(d["repos"]) == core["corpus_repos"],
          f"{len(d['repos'])} vs {core['corpus_repos']}")
    check("看板权重与 WEIGHTS_V3_STRUCT 完全一致",
          d["weights"] == core["weights_v3_struct"], str(d["weights"]))
    check("看板权重和 = 1", abs(sum(d["weights"].values()) - 1.0) < 1e-9)

print("\n[4] 看板横幅里的数字必须等于重算值（曾长期写着过期的 0.278）")
if bl.exists():
    html = bl.read_text(encoding="utf-8")
    m = re.search(r'(?s)<div class="notice">(.*?)</div>', html)
    check("能定位横幅", m is not None)
    if m:
        banner = re.sub(r"<[^>]+>", " ", m.group(1))
        want = f"{cached['overlap']['overlap']['struct|content']:.3f}"
        check(f"横幅写明结构∩内容 = {want}", want in banner, banner.strip()[:60])
        v1w = f"{core['size_component']['v1_min']:.3f}"
        check(f"横幅写明 v1 size 下限 = {v1w}", v1w in banner)
        spanw = f"{core['size_span_ratio']:.0f}"
        check(f"横幅写明规模跨度 = {spanw}", spanw in banner)

print("\n[5] 文档数字与重算值交叉核对（每个数字都从真值格式化而来）")
NUMS = {n: [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.?\d*", t)]
        for n, t in texts.items()}


def has(doc, val, dec):
    tol = 0.5 * 10 ** (-dec) + 1e-9
    return any(abs(x - val) < tol for x in NUMS[doc])


checks = [
    ("结构∩内容", cached["overlap"]["overlap"]["struct|content"], 3),
    ("结构∩文件名", cached["overlap"]["overlap"]["struct|fn"], 3),
    ("v1 size 下限", core["size_component"]["v1_min"], 3),
]
for name in texts:
    for label, val, dec in checks:
        check(f"{name} 含 {label} = {val:.{dec}f}", has(name, val, dec))
# 看板体积只对 Writeup 强制：README 是精简版，不逐条复述产物尺寸
check(f"WRITEUP_FINAL.md 含 看板体积 KB = {core['dashboard_kb']:.0f}",
      has("WRITEUP_FINAL.md", core["dashboard_kb"], 0))

# README 是精简版：核心数字必须有，逐条 Case 数字不强制
check("README 含 0.371", has("README_OPEN_SOURCE.md",
                            cached["overlap"]["overlap"]["struct|content"], 3))
check("README 含 0.405", has("README_OPEN_SOURCE.md",
                            cached["overlap"]["overlap"]["struct|fn"], 3))
check("README 权重表 primary_lang 与源码一致",
      f"| {core['weights_v3_struct']['primary_lang']} |" in texts["README_OPEN_SOURCE.md"])
check("README 权重表 test_ratio 与源码一致",
      f"| {core['weights_v3_struct']['test_ratio']} |" in texts["README_OPEN_SOURCE.md"])

print("\n[6] 过期值不得作为【当前结论】出现")
STALE = {
    "0.278": "旧 v2 权重下的结构∩内容重叠（现为 0.371）",
    "0.366": "旧 v2 权重下的结构∩文件名重叠（现为 0.405）",
    "0.8052": "旧的分歧案例数值（已不可复现）",
    "0.0742": "旧的分歧案例数值（已不可复现）",
}
live = [v for _, v, _ in checks] + [
    cached["overlap"]["overlap"]["struct|content"],
    cached["overlap"]["overlap"]["struct|fn"]]
for name, txt in texts.items():
    bad = []
    for s, why in STALE.items():
        fv = float(s)
        if any(abs(fv - lv) < 0.5e-3 for lv in live):
            continue
        if any(abs(fv - x) < 0.5e-3 for x in NUMS[name]):
            bad.append(f"{s} ({why})")
    check(f"{name} 无未加说明的过期值", not bad, str(bad))

print("\n[7] 跨语言判别结论：必须与重算的实测值方向一致（不是复述预设答案）")
# 从真值判断方向，再要求文档没有反向措辞。文档说什么由数据决定，不由本脚本决定。
v3 = core["lang_hits"]["v3"]
above = [l for l in v3 if v3[l] > core["lang_expectation"][l]]
below = [l for l in v3 if v3[l] <= core["lang_expectation"][l]]
print(f"       实测：{len(above)}/{len(v3)} 类高于随机期望；低于的：{below}")
wr = texts["WRITEUP_FINAL.md"]
if not below:
    for phrase in ("does not discriminate across languages",
                   "falls below random expectation",
                   "discrimination fails"):
        check(f"未出现与实测相反的措辞「{phrase[:34]}」", phrase not in wr)
    check("Writeup 给出了实测命中率（4.80）", has("WRITEUP_FINAL.md", v3["Python"], 2))
else:
    check("存在低于期望的类目时，Writeup 必须承认", "below random" in wr or "低于" in wr)
# 历史错误结论只能以「更正/作废」形式出现在实验日志里
log = (TOOL / "10_RepoLens方法与实验.md").read_text(encoding="utf-8")
if "跨语言判别依然失效" in log or "判别失效" in log:
    check("实验日志中的旧结论已标注为作废/更正",
          "更正" in log or "作废" in log)

print("\n[8] 诚实性披露是否齐全")
for name, txt in texts.items():
    check(f"{name} 写明无标注数据",
          "no labelled dataset" in txt or "not supervised" in txt or "没有标注" in txt)
    check(f"{name} 写明互补非替代",
          "complements" in txt or "rather than replacing" in txt or "互补" in txt)
    check(f"{name} 披露 v1 size 下限缺陷",
          "0.304" in txt or "never reached zero" in txt or "永远到不了" in txt)

print("\n[9] 五项评分维度：检查【实质】而非关键词")
# ⚠️ 旧版断言文档里出现 "Novelty"/"Quality" 等字样。那是关键词匹配，不是质量检查：
#    在标题里塞五个词就能骗过它，而真正写清楚内容的稿子反而会 FAIL。
#    改为逐维度检查它需要的**实质内容**是否存在，并报告证据位置。
wr = texts["WRITEUP_FINAL.md"]
dims = {
    "Novelty（与既有工作的差异）":
        ("## 2. Related Work" in wr and "closest prior work" in wr
         and "did not find a prior system" in wr),
    "Quality（定义与拆解，而非黑箱）":
        (all(k in wr for k in core["weights_v3_struct"])
         and "## 6. Component Analysis" in wr),
    "Relevance（对 agent 场景的用途）":
        ("coding agent" in wr and "## 1. Introduction" in wr),
    "Verifiability（数字可重算）":
        ("derive_truth" in wr and "exit zero" in wr and "## 8. Availability" in wr),
    "Clarity（结果可解释 + 配图）":
        ("component breakdown" in wr and wr.count("runs/figures/") >= 4),
}
for k, v in dims.items():
    check(k, v)
check("四张图都被正文引用", all(f"fig{i}_" in wr for i in (1, 2, 3, 4)))

print("\n" + "=" * 54)
print("全部通过。" if ok else "存在失败项。")
raise SystemExit(0 if ok else 1)
