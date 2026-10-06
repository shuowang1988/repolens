"""校验 dashboard.html：结构完整、数据自洽、可离线打开。"""
import json
import re
import sys
from pathlib import Path

# Resolve paths relative to THIS FILE, not the current working directory.
# Real bug hit on 2026-10-05: running the suite from the repo root made this
# exit=1 because `..` pointed at the wrong place, even though the test passed
# when run from src/. Tests must not depend on cwd.
HERE = Path(__file__).resolve().parent
html = HERE.parent / "runs" / "balanced" / "dashboard.html"
ok = True


def check(label, cond, extra=""):
    global ok
    if not cond:
        ok = False
    print(f"  {'OK ' if cond else 'FAIL'} {label}{(' | ' + extra) if extra else ''}")


print(f"[1] 文件存在与体积")
check("dashboard.html 存在", html.exists())
if not html.exists():
    raise SystemExit(1)
txt = html.read_text(encoding="utf-8")
check(f"体积合理 ({html.stat().st_size/1024:.0f} KB)",
      50 < html.stat().st_size / 1024 < 5000)

print(f"\n[2] 离线自包含（不能有外部依赖）")
check("无外部 JS 引用", "src=\"http" not in txt and "src='http" not in txt)
check("无外部 CSS 引用", "href=\"http" not in txt or "<link" not in txt)
check("数据已内联 (__DATA__ 已替换)", "__DATA__" not in txt)
check("无 fetch/XHR 调用", "fetch(" not in txt and "XMLHttpRequest" not in txt)

print(f"\n[3] HTML 结构完整")
for tag in ("<!DOCTYPE html>", "<head>", "<style>", "<script>", "</html>"):
    check(f"含 {tag}", tag in txt)

print(f"\n[4] 内联数据可解析且自洽")
m = re.search(r"const DATA = (\{.*?\});\n", txt, re.S)
check("能提取 DATA", m is not None)
if m:
    d = json.loads(m.group(1))
    check(f"repos 数量 = {len(d['repos'])}", len(d["repos"]) == 41)
    check(f"sim 覆盖全部仓库 = {len(d['sim'])}", len(d["sim"]) == 41)
    check("权重 8 项且和为 1",
          len(d["weights"]) == 8 and abs(sum(d["weights"].values()) - 1.0) < 1e-9)
    ids = {r["id"] for r in d["repos"]}
    check("sim 的 key 都在 repos 里", set(d["sim"]) == ids)
    # 每个查询的候选不得包含自己
    bad_self = [q for q, rows in d["sim"].items() if any(r["id"] == q for r in rows)]
    check("候选不含自身（自相似已排除）", not bad_self, str(bad_self[:3]))
    # 分数必须降序
    unsorted_q = [q for q, rows in d["sim"].items()
                  if any(rows[i]["score"] < rows[i + 1]["score"] - 1e-9
                         for i in range(len(rows) - 1))]
    check("分数已降序排列", not unsorted_q, str(unsorted_q[:3]))
    # 分量值域
    oor = [1 for rows in d["sim"].values() for r in rows
           for v in r["comp"].values() if v < -1e-9 or v > 1 + 1e-9]
    check("分量值均在 [0,1]", not oor)
    # 每个候选都要有解释文本
    noexp = [r["id"] for rows in d["sim"].values() for r in rows if not r.get("why")]
    check("每条候选都有「为什么像」", not noexp, str(noexp[:3]))

print(f"\n[5] 诚实性披露是否在页面上")
# ⚠️ 断言必须随实测结论更新，而且不能靠关键词匹配。
#    曾断言"不做跨语言判别"，那条来自 lang_crosscheck.py 的算术 bug。
#    现在只检查【方法边界横幅】里的数字是否等于重算真值，
#    并检查英文披露是否存在（页面已全英文）。
import json as _json
from pathlib import Path as _Path
import sys as _sys
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import derive_truth as _dt

_truth = _json.loads((_Path(__file__).resolve().parent.parent / "runs" / "balanced"
                      / "derived_truth.json").read_text(encoding="utf-8"))
_core = _dt.core_truth()
banner_m = re.search(r'(?s)<div class="notice">(.*?)</div>', txt)
check("能定位方法边界横幅", banner_m is not None)
if banner_m:
    banner = banner_m.group(1)
    ov_want = f"{_truth['overlap']['overlap']['struct|content']:.3f}"
    check(f"横幅写明 Top-5 重叠 = {ov_want}", ov_want in banner)
    v1_want = f"{_core['size_component']['v1_min']:.3f}"
    check(f"横幅写明 v1 size 下限 = {v1_want}", v1_want in banner)
    span_want = f"{_core['size_span_ratio']:.0f}"
    check(f"横幅写明规模跨度 = {span_want}", span_want in banner)
    check("横幅未写死过期重叠值 0.278", "0.278" not in banner)
for kw in ("no labelled dataset", "not supervised", "complementary"):
    check(f"页面写明「{kw}」", kw in txt)
check("页面未声称跨语言判别失效",
      "does not discriminate across languages" not in txt)

print(f"\n[5b] 正文引用的那条解释必须真的能在看板里渲染出来")
# WRITEUP_FINAL.md 逐字引用了 explain_v2() 的输出。如果哪天改了文案或权重，
# 引用就会与产物脱节 —— 这里反查看板内联数据里是否真的存在该字符串。
_wu = (_Path(__file__).resolve().parent.parent / "WRITEUP_FINAL.md").read_text(encoding="utf-8")
_quoted = re.findall(r"`(\[[a-z ]+similarity\][^`]+)`", _wu, re.S)
check(f"正文含 {len(_quoted)} 条被引用的解释", len(_quoted) >= 1)
for q in _quoted:
    # Markdown 会把长句折行，比较前必须归一化空白
    norm = " ".join(q.split())
    check(f"看板内联数据含该解释 | {norm[:56]}...", norm in " ".join(txt.split()))

print("\n[6] 交互元素存在")
for kw in ("renderList", "renderMain", "comp_label", "topdirs"):
    check(f"含 {kw}", kw in txt)
check("页面已全英文（无中文字符）",
      not re.search(r"[\u4e00-\u9fff]", txt))

print("\n" + "=" * 52)
print("全部通过。" if ok else "存在失败项。")
raise SystemExit(0 if ok else 1)
