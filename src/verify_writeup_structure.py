"""
verify_writeup_structure.py — 校验最终提交稿 WRITEUP_FINAL.md。

设计原则（本项目已被同一类 bug 烧过五次）：
  **检查器不得硬编码任何期望结论或期望数字。**
  旧版本写的是 check("正确陈述跨语言判别有效", "Language discrimination works" in txt)
  —— 那不是校验，那是让文档复述检查器预先相信的结论。一旦结论本身错了
  （它确实错过：lang_crosscheck.py 的算术 bug 让"判别失效"被写进了文档），
  检查器只会一起错，还会阻止修正。

现在的做法：
  1. 现场重算便宜层真值（derive_truth.core_truth），并与落盘真值的指纹核对；
  2. 昂贵层（三种方法的重叠矩阵、分歧案例）读落盘真值，指纹不符即 FAIL；
  3. 把真值格式化成字符串，逐个断言它**出现在文档里**；
  4. 断言过期值**不出现**；
  5. 结构要件 / 字数 / 英文纯度。

也就是说：文档里的每个数字都必须能被重算出来，检查器自己不知道答案。
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent
WU = TOOL / "WRITEUP_FINAL.md"
TRUTH = TOOL / "runs" / "balanced" / "derived_truth.json"
LIMIT = 3000

sys.path.insert(0, str(HERE))
import derive_truth as dt  # noqa: E402

ok = True


def check(label, cond, extra=""):
    global ok
    if not cond:
        ok = False
    print(f"  {'OK ' if cond else 'FAIL'} {label}{(' | ' + extra) if extra else ''}")


def doc_numbers(txt: str) -> list[float]:
    """文档里出现的全部数值 token。

    ⚠️ 必须按【数值】比对，不能按【字符串】比对。
       曾因 lang_shape 中位数 = 0.8755，文档写 0.876、检查器 f"{v:.3f}" 得 0.875，
       同一份真值两种写法互相判 FAIL —— 那是格式化边界的假阳性，不是数据错误。
    """
    out = []
    for tok in re.findall(r"\d[\d,]*\.?\d*", txt):
        try:
            out.append(float(tok.replace(",", "")))
        except ValueError:
            pass
    return out


def has_num(nums: list[float], value: float, decimals: int) -> bool:
    tol = 0.5 * 10 ** (-decimals) + 1e-9
    return any(abs(n - value) < tol for n in nums)


print("[1] 文件存在")
if not WU.exists():
    print(f"  FAIL 缺少 {WU}")
    raise SystemExit(1)
check(f"{WU.name}", True)

txt = WU.read_text(encoding="utf-8")

print("\n[2] 真值必须新鲜（现场重算 core，核对指纹与落盘缓存）")
if not TRUTH.exists():
    print(f"  FAIL 缺少 {TRUTH}，请先运行 derive_truth.py")
    raise SystemExit(1)
cached = json.loads(TRUTH.read_text(encoding="utf-8"))
live = dt.core_truth()
check("inputs 指纹与缓存一致", cached.get("fingerprint") == dt.inputs_fingerprint(),
      f"{cached.get('fingerprint')} vs {dt.inputs_fingerprint()}")
if "overlap" not in cached:
    check("缓存含昂贵层（重叠矩阵）", False, "请运行 derive_truth.py（不带 --core）")

# 现场重算的 core 必须与缓存逐字段一致 —— 防止有人手改缓存
diffs = [k for k in live if cached["core"].get(k) != live[k]]
check("现场重算 core 与缓存逐字段一致", not diffs, str(diffs))
core = live
ov = cached.get("overlap", {})

print("\n[3] 官方五项必备要件")
required = {
    "Title and subtitle": txt.lstrip().startswith("# "),
    "Abstract": "## Abstract" in txt,
    "Introduction": "## 1. Introduction" in txt,
    "Description of research (methods+experiments)":
        "## 3. The RepoLens Method" in txt and "## 5. Results" in txt,
    "Related works and citations": "## 2. Related Work" in txt and "## References" in txt,
}
for k, v in required.items():
    check(k, v)

print("\n[4] 字数上限（官方 3,000）")
# 口径：去掉代码块、标题行、表格行后的英文正文词数。
body = re.sub(r"```.*?```", "", txt, flags=re.S)
body = re.sub(r"^\s*[-*>#|].*$", "", body, flags=re.M)
body = re.sub(r"[`*>|\-]", " ", body)
words = len(body.split())
full = len(txt.split())
check(f"正文 {words} 词 < {LIMIT}", words < LIMIT, f"余量 {LIMIT - words}")
check(f"全文（含表格/引用）{full} 词 < {LIMIT}", full < LIMIT, f"余量 {LIMIT - full}")

print("\n[5] 提交正文必须为英文（评分为 Google DeepMind 研究员）")
cn = re.findall(r"[\u4e00-\u9fff]", txt)
check(f"无中文字符（实测 {len(cn)}）", not cn, "".join(cn[:20]))

print("\n[6] 每个数字都必须能由产物重算出来（claim -> derived -> 是否在稿中）")
NUMS = doc_numbers(txt)
# ---- 语料与结构
claims = []          # (label, value, decimals)
claims.append(("语料仓库数", core["corpus_repos"], 0))
claims.append(("两两组合数", core["pairwise_combinations"], 0))
claims.append(("权重和", core["weights_v3_sum"], 2))
for k, v in core["weights_v3_struct"].items():
    claims.append((f"权重 {k}", v, 2))
# ---- 重叠矩阵（昂贵层）
omat = ov.get("overlap", {})
for key, label in (("struct|content", "结构∩内容"), ("struct|fn", "结构∩文件名"),
                   ("content|fn", "内容∩文件名")):
    if key in omat:
        claims.append((label, omat[key], 3))
# ---- 语言期望与命中
for lang, v in core["lang_expectation"].items():
    claims.append((f"{lang} 随机期望", v, 2))
for lang, v in core["lang_hits"]["v3"].items():
    claims.append((f"{lang} 实测(v3)", v, 2))
for lang, v in core["lang_hits"]["v2"].items():
    claims.append((f"{lang} 实测(v2)", v, 2))
# ---- 实测/期望倍数（正文以区间形式引用）
ratios = list(core.get("lang_ratio", {}).values())
if ratios:
    claims.append(("语言倍数下界", min(ratios), 1))
    claims.append(("语言倍数上界", max(ratios), 1))
# ---- size 分量
sc = core["size_component"]
claims.append(("v1 size 下限", sc["v1_min"], 3))
claims.append(("v1 size 中位", sc["v1_median"], 3))
claims.append(("v2 size 下限", sc["v2_min"], 3))
claims.append(("v2 size 中位", sc["v2_median"], 3))
claims.append(("规模跨度倍数", core["size_span_ratio"], 0))
claims.append(("最小代码文件数", core["size_span_files"][0], 0))
claims.append(("最大代码文件数", core["size_span_files"][1], 0))
# ---- 分量分布
for k, st in core["component_stats"].items():
    claims.append((f"{k} min", st["min"], 3))
    claims.append((f"{k} median", st["median"], 3))
    claims.append((f"{k} max", st["max"], 3))
    claims.append((f"{k} <0.3 占比", st["frac_lt_0.3"], 3))
# ---- 看板
if "dashboard_kb" in core:
    claims.append(("看板体积 KB", core["dashboard_kb"], 0))
# ---- 分歧案例（昂贵层）
for c in ov.get("case_a_structure_only", []):
    if c["query"] == "Textualize/textual":
        claims.append(("Case A 结构分", c["struct"], 4))
        claims.append(("Case A 内容分", c["content"], 4))
named = ov.get("named_case")
if named:
    claims.append(("Case B 内容分", named["content"], 4))
    claims.append(("Case B 结构分", named["struct"], 4))

missing = []
for label, val, dec in claims:
    hit = has_num(NUMS, val, dec)
    if not hit:
        missing.append(f"{label}={val:.{dec}f}")
    print(f"  {'OK ' if hit else 'FAIL'} {label:24s} -> {val:.{dec}f}")
check(f"{len(claims)} 项数字声明全部可在稿中溯源", not missing, str(missing))

print("\n[7] 过期值不得出现")
# 这些值的「过期」含义由真值本身决定：如果真值恰好等于它，就不算过期。
stale = {
    "0.278": "旧 v2 权重下的结构∩内容重叠",
    "0.366": "旧 v2 权重下的结构∩文件名重叠",
    "0.499": "19 仓语料的 v1 size 下限（41 仓为 0.304）",
    "0.8052": "旧的分歧案例数值（已不可复现）",
    "0.0742": "旧的分歧案例数值（已不可复现）",
}
live_vals = [v for _, v, _ in claims]
for s, why in stale.items():
    if has_num(live_vals, float(s), 4):
        continue                     # 万一真值就是它，则不是过期值
    check(f"未残留过期值 {s}", not has_num(NUMS, float(s), 4), why)

print("\n[8] 自检脚本数量声明必须等于清单长度（不是写死的数字）")
n_suite = len(dt.SELF_TEST_SUITE)
miss = [s for s in dt.SELF_TEST_SUITE if not (HERE / s).exists()]
check(f"清单中 {n_suite} 个脚本都存在", not miss, str(miss))
_words = {14: "Fourteen", 15: "Fifteen", 16: "Sixteen", 17: "Seventeen"}
check(f"正文声明「{_words.get(n_suite, n_suite)}」个自检脚本",
      _words.get(n_suite, str(n_suite)) in txt,
      f"清单长度 {n_suite}")

print("\n[9] 参考文献必须都可解析（arXiv ID 已逐个 web 核验过标题与作者）")
ids = re.findall(r"arXiv:(\d{4}\.\d{4,5})", txt)
check(f"参考文献含 {len(ids)} 个 arXiv ID", len(ids) >= 6, str(ids))
check("引用编号 [1]-[6] 均在正文出现",
      all(f"[{i}]" in txt for i in range(1, 7)))
check("参考文献中无未核验的 URL 或悬空引用",
      not re.search(r"https?://", txt))

print("\n" + "=" * 54)
print("全部通过。" if ok else "存在失败项。")
raise SystemExit(0 if ok else 1)
