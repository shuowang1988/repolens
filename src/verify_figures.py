"""
verify_figures.py — 校验配图与实测数据一致，且图上没有任何写死的过期结论。

起因（2026-10-05）：调高 primary_lang 权重后重算了 Fig 1 的重叠矩阵，
真值变成 0.371 / 0.405，但图上的箭头标注仍硬写着旧的 "0.278"。
这类错误肉眼很难发现 —— 图能正常渲染，只是数字在说谎。

第二次踩坑（同一类）：Fig 2 的**标题**写死成「实测低于随机期望」。
那句结论本身来自 lang_crosscheck.py 的算术 bug；bug 修好后条形图变成
4.80 vs 1.83（远高于期望），标题却还在说"低于"，
而且 ylim = max(期望)*1.35 把高柱直接截断。
**图能渲染，检查器全过，交付物自相矛盾。**

因此本检查器做四件事：
  1. 四张图存在且体积合理
  2. 重算图上要呈现的每个数字，与落盘真值核对
  3. 用 AST 扫描 make_figures.py —— 区分「代码」与「注释/文档字符串」，
     确保渲染出来的字符串里没有写死的过期结论
  4. 回归守卫：标题由数据判定、ylim 同时考虑两组数据
"""

import ast
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent
FIG = TOOL / "runs" / "figures"
SRC = HERE / "make_figures.py"
TRUTH = TOOL / "runs" / "balanced" / "derived_truth.json"

sys.path.insert(0, str(HERE))
import derive_truth as dt  # noqa: E402

ok = True


def check(label, cond, extra=""):
    global ok
    if not cond:
        ok = False
    print(f"  {'OK ' if cond else 'FAIL'} {label}{(' | ' + extra) if extra else ''}")


print("[1] 四张图存在")
expected = ["fig1_overlap.png", "fig2_language.png",
            "fig3_components.png", "fig4_size_fix.png"]
for f in expected:
    p = FIG / f
    check(f"{f}", p.exists() and p.stat().st_size > 5000,
          f"{p.stat().st_size/1024:.0f} KB" if p.exists() else "missing")

print("\n[2] 图上的数字 = 重算值")
core = dt.core_truth()
cached = json.loads(TRUTH.read_text(encoding="utf-8"))
check("inputs 指纹一致", cached.get("fingerprint") == dt.inputs_fingerprint())
diffs = [k for k in core if cached["core"].get(k) != core[k]]
check("现场重算 core 与缓存一致", not diffs, str(diffs))

ov = cached["overlap"]["overlap"]
# (label, 重算值, 图上呈现值, 小数位) —— 容差按呈现的小数位取半个最小单位
fig_nums = [
    ("Fig1 结构∩内容", ov["struct|content"], 0.371, 3),
    ("Fig1 结构∩文件名", ov["struct|fn"], 0.405, 3),
    ("Fig1 内容∩文件名", ov["content|fn"], 0.322, 3),
    ("Fig4 v1 size 下限", core["size_component"]["v1_min"], 0.304, 3),
    ("Fig4 v2 size 下限", core["size_component"]["v2_min"], 0.000, 3),
    ("Fig2 Python 实测", core["lang_hits"]["v3"]["Python"], 4.80, 2),
    ("Fig2 Python 期望", core["lang_expectation"]["Python"], 1.83, 2),
    ("Fig2 Go 实测", core["lang_hits"]["v3"]["Go"], 3.57, 2),
    ("Fig3 两两组合数", core["pairwise_combinations"], 820, 0),
    ("Fig4 规模跨度", core["size_span_ratio"], 1640, 0),
]
for label, got, want, dec in fig_nums:
    tol = 0.5 * 10 ** (-dec) + 1e-9
    check(f"{label} = {want:g}", abs(got - want) < tol, f"重算 {got}")

print("\n[3] 源码里没有写死的过期结论（AST：只看代码字符串，不看注释与文档字符串）")
src = SRC.read_text(encoding="utf-8")
tree = ast.parse(src)
doc_nodes = set()
for node in ast.walk(tree):
    for attr in ("body",):
        body = getattr(node, attr, None)
        if (isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef))
                and body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            doc_nodes.add(id(body[0].value))
code_strings = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in doc_nodes]
blob = "\n".join(code_strings)
check(f"提取到 {len(code_strings)} 个代码字符串（注释与文档字符串已排除）",
      len(code_strings) > 10)

stale = {
    "0.278": "旧 v2 权重下的重叠值，现为 0.371",
    "0.499": "19 仓语料的 size 下限，41 仓为 0.304",
    "155": "旧语料的规模跨度",
    "0.8052": "旧的分歧案例数值",
    "0.0742": "旧的分歧案例数值",
    "低于随机期望": "被 bug 推翻的旧结论",
    "永远到不了": "过期的措辞（现由数据算出）",
}
for s, why in stale.items():
    check(f"代码字符串中无「{s}」", s not in blob, why)

print("\n[4] 回归守卫：曾经真实踩到的两个渲染 bug")
# bug A：Fig1 的箭头标注写死字符串，改权重后图上自相矛盾
check("Fig1 标注由 mat 变量算出", 'annotate(f"{key:.3f}"' in src)
# bug B：Fig4 的标题倍数写死旧语料的数字
check("Fig4 倍数由 spans 算出", "ratio = spans[-1]" in src)
# bug C：Fig2 标题写死结论（必须由 exp/act 判定）
check("Fig2 结论由数据判定（含 above/verdict 计算）",
      "above = sum(1 for e, a in zip(exp, act) if a > e)" in src
      and "verdict =" in src)
# bug D：Fig2 的 ylim 只按期望设上限，把实测的高柱截断
check("Fig2 ylim 同时考虑 exp 与 act（防截断）",
      "set_ylim(0, max(max(exp), max(act))" in src)

print("\n[5] 实测真值速记（供人工核对）")
print(f"  结构∩内容 = {ov['struct|content']:.3f}, 结构∩文件名 = {ov['struct|fn']:.3f}, "
      f"内容∩文件名 = {ov['content|fn']:.3f}")
_h = core["lang_hits"]["v3"]
_e = core["lang_expectation"]
print("  v3 权重跨语言：" + " / ".join(
    f"{k} {_h[k]:.2f}（期望 {_e[k]:.2f}）" for k in ("Python", "Rust", "Go", "Java")))
_h2 = core["lang_hits"]["v2"]
print("  v2 权重跨语言：" + " / ".join(f"{k} {_h2[k]:.2f}" for k in _h2))
print(f"  v1 size 下限 = {core['size_component']['v1_min']:.3f}，"
      f"v2 = {core['size_component']['v2_min']:.3f}，"
      f"规模跨度 = {core['size_span_ratio']:.0f}x")
print("  ⚠️ 改权重会同时改变上述数字，必须重跑 derive_truth.py 并同步文档")

print("\n" + "=" * 54)
print("全部通过。" if ok else "存在失败项。")
raise SystemExit(0 if ok else 1)
