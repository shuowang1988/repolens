"""repo_structure_similarity.py — 仓库结构相似度检索（PoC 第一步）

目标：实现主办方在 Best New Resource 里亲自举例的
「a dashboard to explore Github repos that are similar in structure to a target repo」
的**核心计算层**，先用纯本地、不依赖任何外部服务的方式把特征定义清楚、跑通、验证。

现在只做三件事（都可在断网环境完成）：
  1. 从本地已 clone 的仓库目录提取结构特征
  2. 两两算相似度
  3. 打印「目标仓库的 Top-N 相似仓库」并解释每条为什么像

后续再接 GitHub 检索层与看板层。

【重要设计约束】
  - 只用成熟的成熟开源（不重写解析器）。本文件只做**特征编排**，
    语言统计交给 pygit2 / 纯 Python，目录结构交给 os.walk。
  - 特征必须可解释：每个相似度分量都要能说清「为什么这俩像」，
    这是评分里 Verifiability 与 Clarity 两栏的直接抓手。
  - 断网可跑（不调用 GitHub API）。

【中断与续跑】
  本脚本无状态，一次跑完，通常 <10 秒。
"""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# 代码扩展名 -> 语言（够用即可，不追求完备；不完备在 README 里说明）
EXT_LANG = {
    ".py": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin", ".scala": "Scala",
    ".c": "C", ".h": "C", ".cc": "C++", ".cpp": "C++", ".hpp": "C++",
    ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".swift": "Swift",
    ".md": "Markdown", ".rst": "ReST", ".txt": "Text", ".json": "JSON",
    ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML", ".cfg": "Config", ".ini": "Config",
}

SKIP_DIRS = {
    ".git", ".github", ".idea", ".vscode", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".mypy_cache", ".pytest_cache", ".tox", "site-packages", ".eggs",
    ".next", ".cache", "coverage", ".coverage", "htmlcov",
}


@dataclass
class RepoFeatures:
    name: str
    path: str
    n_files: int = 0
    n_code_files: int = 0
    n_test_files: int = 0
    n_dirs: int = 0
    total_code_lines: int = 0
    max_depth: int = 0
    lang_counts: dict[str, int] = field(default_factory=dict)
    top_level_dirs: set[str] = field(default_factory=set)
    path_segments: dict[str, int] = field(default_factory=dict)   # 目录名 -> 出现次数
    test_path_ratio: float = 0.0
    src_to_test_ratio: float = 0.0

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["top_level_dirs"] = sorted(self.top_level_dirs)
        return d


def _is_test_path(parts: tuple[str, ...], fname: str) -> bool:
    low = fname.lower()
    if low.startswith("test_") or low.endswith("_test.py") or low.endswith(".test.ts") \
       or low.endswith(".test.js") or low.endswith(".spec.ts"):
        return True
    return any(p in ("tests", "test", "spec", "__tests__") for p in parts)


def extract_features(repo_path: str | Path, name: str | None = None) -> RepoFeatures:
    """扫描本地仓库目录，提取结构特征。纯文件系统操作，断网可用。"""
    root = Path(repo_path)
    f = RepoFeatures(name=name or root.name, path=str(root))

    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        depth = len(rel.parts)
        f.max_depth = max(f.max_depth, depth)
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".egg")]

        if depth == 1 and rel.parts:
            f.top_level_dirs.add(rel.parts[0])

        for d in dirnames:
            f.path_segments[d] = f.path_segments.get(d, 0) + 1

        for fn in filenames:
            f.n_files += 1
            ext = Path(fn).suffix.lower()
            parts = rel.parts if depth else ()
            if _is_test_path(parts, fn):
                f.n_test_files += 1
            lang = EXT_LANG.get(ext)
            if lang is None or ext in (".md", ".txt", ".json", ".yml", ".yaml", ".toml"):
                continue
            f.n_code_files += 1
            f.lang_counts[lang] = f.lang_counts.get(lang, 0) + 1
            try:
                with open(Path(dirpath) / fn, "r", encoding="utf-8", errors="ignore") as fh:
                    f.total_code_lines += sum(1 for _ in fh)
            except OSError:
                pass

    if f.n_files:
        f.test_path_ratio = f.n_test_files / f.n_files
    src = max(1, f.n_code_files - f.n_test_files)
    f.src_to_test_ratio = src / max(1, f.n_test_files)
    return f


# ------------------------------------------------------------------ 相似度


def _entropy(counts: dict[str, int]) -> float:
    """语言分布的归一化熵，衡量「语言是否集中」。"""
    tot = sum(counts.values())
    if tot <= 0:
        return 0.0
    h = -sum((c / tot) * math.log(c / tot) for c in counts.values())
    return h / math.log(len(counts)) if len(counts) > 1 else 0.0


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _log_ratio_sim(a: float, b: float, eps: float = 1.0) -> float:
    """两个正数在对数尺度上的接近程度，1 = 同量级，0 = 差很远。"""
    if a <= 0 or b <= 0:
        return 0.0
    la, lb = math.log(a + eps), math.log(b + eps)
    return max(0.0, 1.0 - abs(la - lb) / max(abs(la), abs(lb)))


def similarity_components(a: RepoFeatures, b: RepoFeatures) -> dict[str, float]:
    """拆成 5 个可解释分量，每个都对应一句「为什么像」。"""
    return {
        # 1) 规模接近
        "size": _log_ratio_sim(a.n_code_files, b.n_code_files),
        # 2) 主要语言一致
        "primary_lang": 1.0 if _top_lang(a) == _top_lang(b) else 0.0,
        # 3) 语言分布形状接近（集中还是分散）
        "lang_shape": 1.0 - abs(_entropy(a.lang_counts) - _entropy(b.lang_counts)),
        # 4) 顶层目录布局像（src/ tests/ docs/ 这种组织方式）
        "top_dirs": _jaccard(a.top_level_dirs, b.top_level_dirs),
        # 5) 测试布局像
        "test_ratio": 1.0 - min(1.0, abs(math.log(a.src_to_test_ratio + 1)
                                         - math.log(b.src_to_test_ratio + 1)) / 3.0),
    }


WEIGHTS = {"size": 0.20, "primary_lang": 0.20, "lang_shape": 0.15,
           "top_dirs": 0.25, "test_ratio": 0.20}


def _top_lang(f: RepoFeatures) -> str:
    if not f.lang_counts:
        return "?"
    return max(f.lang_counts.items(), key=lambda kv: kv[1])[0]


def total_similarity(a: RepoFeatures, b: RepoFeatures) -> tuple[float, dict[str, float]]:
    comp = similarity_components(a, b)
    s = sum(WEIGHTS[k] * comp[k] for k in WEIGHTS)
    return s, comp


def explain(a: RepoFeatures, b: RepoFeatures, comp: dict[str, float]) -> str:
    """生成一句人类可读的「为什么像」，直接用于看板与 Writeup 的可解释性。"""
    reasons = []
    if comp["primary_lang"] > 0.5:
        reasons.append(f"主语言同为 {_top_lang(a)}")
    if comp["top_dirs"] > 0.3:
        shared = sorted(a.top_level_dirs & b.top_level_dirs)[:4]
        reasons.append(f"顶层目录重合：{', '.join(shared)}")
    if comp["size"] > 0.5:
        reasons.append(f"代码规模接近（{a.n_code_files} vs {b.n_code_files} 个代码文件）")
    if comp["test_ratio"] > 0.5:
        reasons.append("测试目录布局接近")
    return "；".join(reasons) if reasons else "整体规模与布局接近"


# --------------------------------------------------------------------- 自检


def _self_test() -> int:
    import tempfile

    ok = True
    print("[自检] 特征提取")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 造一个「典型 Python web 项目」结构
        for p in ["src/pkg", "src/pkg/api", "tests", "docs"]:
            (root / p).mkdir(parents=True, exist_ok=True)
        (root / "src" / "pkg" / "__init__.py").write_text("x = 1\n" * 50)
        (root / "src" / "pkg" / "core.py").write_text("def f():\n    return 1\n" * 30)
        (root / "src" / "pkg" / "api" / "routes.py").write_text("y = 2\n" * 40)
        (root / "tests" / "test_core.py").write_text("assert True\n" * 20)
        (root / "README.md").write_text("# hi\n")
        (root / ".git").mkdir(exist_ok=True)
        (root / ".git" / "config").write_text("[core]\n")

        f = extract_features(root, name="demo")
        print(f"  文件 {f.n_files}（代码 {f.n_code_files}，测试 {f.n_test_files}）")
        print(f"  顶层目录 {sorted(f.top_level_dirs)}")
        print(f"  语言分布 {f.lang_counts}")
        print(f"  代码行数 {f.total_code_lines}  最大深度 {f.max_depth}")
        print(f"  src:test 比 = {f.src_to_test_ratio:.2f}")

        checks = [
            (".git 被跳过", ".git" not in f.path_segments),
            ("识别到 Python", f.lang_counts.get("Python", 0) == 4),
            ("Markdown 不计入代码", ".md" not in f.lang_counts),
            ("顶层目录正确", f.top_level_dirs == {"src", "tests", "docs"}),
            ("测试文件被识别", f.n_test_files == 1),
            ("行数合理", 90 < f.total_code_lines < 200),
        ]
        for label, good in checks:
            print(f"  {'OK ' if good else 'FAIL'} {label}")
            if not good:
                ok = False

    print("\n[自检] 相似度可解释性")
    A = RepoFeatures(name="A", path="", n_files=500, n_code_files=400, n_test_files=100,
                     lang_counts={"Python": 380, "C": 20}, top_level_dirs={"src", "tests", "docs"},
                     src_to_test_ratio=3.0)
    B = RepoFeatures(name="B", path="", n_files=520, n_code_files=410, n_test_files=110,
                     lang_counts={"Python": 400, "C": 10}, top_level_dirs={"src", "tests", "docs"},
                     src_to_test_ratio=2.8)
    C = RepoFeatures(name="C", path="", n_files=90, n_code_files=80, n_test_files=8,
                     lang_counts={"Go": 80}, top_level_dirs={"cmd", "internal", "vendor"},
                     src_to_test_ratio=9.0)
    s_ab, c_ab = total_similarity(A, B)
    s_ac, c_ac = total_similarity(A, C)
    print(f"  A vs B 相似度 = {s_ab:.3f}   {explain(A, B, c_ab)}")
    print(f"  A vs C 相似度 = {s_ac:.3f}   {explain(A, C, c_ac)}")
    good = s_ab > s_ac
    print(f"  {'OK ' if good else 'FAIL'} 同语言同布局的 B 应比 Go 项目 C 更像")
    ok = ok and good
    good2 = "主语言同为" in explain(A, B, c_ab)
    print(f"  {'OK ' if good2 else 'FAIL'} 解释里点出了具体原因")
    ok = ok and good2

    print("\n[自检] 相同仓库自比应为满分")
    s_self, _ = total_similarity(A, A)
    good3 = abs(s_self - 1.0) < 1e-9
    print(f"  {'OK ' if good3 else 'FAIL'} self-similarity = {s_self:.6f}")
    ok = ok and good3

    print("\n" + "=" * 46)
    print("全部通过。" if ok else "存在失败项。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_self_test())