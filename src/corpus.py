"""
corpus.py — RepoLens 候选仓库的**克隆管理层**（可中断续跑）

这个模块只管一件事：把一批 GitHub 仓库**可靠地**拉到本地，允许随时中断。
相似度计算在 repo_structure_similarity.py，两者刻意分开——
因为克隆是「慢且会失败」的部分，必须单独做检查点。

为什么需要它（实测踩过的坑）：
  - 网络会断、GitHub 会限流、磁盘会满。裸 `git clone` 循环一旦中断，
    前面成功克隆的成果就白费了，重跑还要重来一遍。
  - 用 --depth 1 可以显著省时间和磁盘（结构分析只需要文件树，不需要历史）。
  - 失败的仓库必须记下来且**不重复重试**，否则限流会越陷越深。

【中断与续跑】
  中断：Ctrl+C，或直接关进程。
  续跑：重跑同一条命令。会读 state/clone_state.jsonl 跳过已完成的仓库。
  已完成判定：目标目录存在且非空（避免把半截目录当成功）。
  失败仓库：记入 failed 列表，重跑时**默认跳过**，除非传 --retry-failed。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# 状态文件读写要容忍 BOM 与半行（Windows 环境常见）
STATE_NAME = "clone_state.jsonl"


def _read_state(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """返回 (成功的 slug->本地目录, 失败的 slug->原因)。"""
    done: dict[str, str] = {}
    failed: dict[str, str] = {}
    if not path.exists():
        return done, failed
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue                      # 崩溃时的半行
            if not isinstance(rec, dict):
                continue                      # 被写成数组/标量的坏行，跳过而不是崩
            slug = str(rec.get("slug", ""))
            if not slug:
                continue
            # 后写的记录覆盖先写的：成功会把之前同 slug 的失败覆盖掉，反之亦然。
            # 否则一次「先失败后成功」的正常重试会让该仓库同时出现在两个表里。
            failed.pop(slug, None)
            done.pop(slug, None)
            if rec.get("ok"):
                done[slug] = str(rec.get("info", ""))
            else:
                failed[slug] = str(rec.get("info", ""))[:200]
    return done, failed


def _append_state(path: Path, slug: str, ok: bool, info: str) -> None:
    rec = {"slug": slug, "ok": ok, "info": info, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()


def _looks_cloned(d: Path) -> bool:
    """目录存在且非空才算克隆成功（防止把半截目录当完成）。"""
    if not d.exists() or not d.is_dir():
        return False
    try:
        return any(d.iterdir())
    except OSError:
        return False


def clone_one(repo: str, dest_root: Path, timeout: int = 300) -> tuple[bool, str]:
    """克隆单个仓库。repo 形如 'owner/name'。

    用 --depth 1 --single-branch：结构分析只需要文件树，不需要 git 历史。
    """
    dest = dest_root / repo.replace("/", "__")
    if _looks_cloned(dest):
        return True, "already"

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():                      # 残留的半截目录，先清掉
        shutil.rmtree(dest, ignore_errors=True)

    url = f"https://github.com/{repo}.git"
    cmd = [
        "git", "clone", "--depth", "1", "--single-branch",
        "--quiet", url, str(dest),
    ]
    # ⚠️ 必须禁用交互式凭据提示。
    # 实测踩过：对不存在的 owner/repo，git 会尝试弹用户名/密码并**无限等待**，
    # 整个批量流程就卡死在这里（不是超时，是挂起）。加上 GIT_TERMINAL_PROMPT=0
    # 与 GIT_ASKPASS 后它会立刻以非 0 退出码失败，我们才能正常记入失败表。
    env = dict(os.environ)
    env.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "",
        "GCM_INTERACTIVE": "never",
    })
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        shutil.rmtree(dest, ignore_errors=True)
        return False, f"timeout {timeout}s"
    if p.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        err = p.stderr.decode("utf-8", "ignore").strip().splitlines()
        return False, (err[-1] if err else f"git exit {p.returncode}")
    if not _looks_cloned(dest):
        return False, "clone 结束但目录为空"
    return True, str(dest)


def free_gb(path: Path) -> float:
    try:
        usage = shutil.disk_usage(path)
        return usage.free / 1024 ** 3
    except OSError:
        return 999.0


def _dir_size(p: str | Path) -> int:
    """目录总字节数。用于语料体积上限保护。"""
    try:
        return sum(f.stat().st_size for f in Path(p).rglob("*")
                   if f.is_file())
    except OSError:
        return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", required=True, help="仓库清单文件，每行一个 owner/name，# 开头为注释")
    ap.add_argument("--dest", required=True, help="克隆目标目录")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--retry-failed", action="store_true", help="重跑时连之前失败的也再试")
    ap.add_argument("--min-free-gb", type=float, default=5.0, help="全局剩余空间低于此值则停止")
    ap.add_argument("--max-corpus-gb", type=float, default=10.0,
                    help="语料目录自身体积上限（GB），超过则停止。"
                         "见 99_common\\磁盘安全策略.md：500 个仓库约 6 GB，"
                         "超过 10 GB 应先向用户报备")
    args = ap.parse_args()

    # utf-8-sig：Windows 用 Set-Content -Encoding UTF8 写出的清单带 BOM，
    # 若不剥掉，BOM 会被算进仓库名首字符，导致 URL 变成 ".../﻿owner/name" 而 100% 失败。
    repos: list[str] = []
    for line in Path(args.list).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip().lstrip("﻿").strip()
        if line and not line.startswith("#") and "/" in line:
            repos.append(line)

    dest_root = Path(args.dest)
    dest_root.mkdir(parents=True, exist_ok=True)
    state = dest_root / "state" / STATE_NAME
    done, failed = _read_state(state)
    print(f"[corpus] 清单 {len(repos)} 个仓库；已完成 {len(done)}，失败 {len(failed)}")

    todo = [r for r in repos
            if r not in done and (args.retry_failed or r not in failed)]
    skipped_failed = len(repos) - len(todo) - len([r for r in repos if r in done])
    if skipped_failed > 0:
        print(f"[corpus] 其中 {skipped_failed} 个之前失败，按 --retry-failed 规则跳过")
    print(f"[corpus] 本次待处理 {len(todo)}")

    ok_n = fail_n = 0
    for i, repo in enumerate(todo, start=1):
        # 磁盘保护：同时看「全局余量」与「本次语料目录已用体积」。
        # 只看全局不够——语料本身可能悄悄长到几十 GB。
        if free_gb(dest_root) < args.min_free_gb:
            print(f"[corpus] !! 剩余空间不足 {args.min_free_gb} GB，停止。"
                  f"已完成的保留，下次续跑会跳过。")
            break
        used_gb = sum(
            _dir_size(p) for p in (done.values() if isinstance(done, dict) else [])
            if p and Path(p).exists()
        ) / 1024 ** 3
        if used_gb > args.max_corpus_gb:
            print(f"[corpus] !! 语料目录已达 {used_gb:.2f} GB，超过上限 "
                  f"{args.max_corpus_gb} GB，停止。"
                  f"（见 99_common\\磁盘安全策略.md）")
            break
        ok, info = clone_one(repo, dest_root, timeout=args.timeout)
        _append_state(state, repo, ok, info)
        if ok:
            done[repo] = info
            ok_n += 1
        else:
            failed[repo] = info
            fail_n += 1
        print(f"[corpus] {i}/{len(todo)} {repo:45s} {'OK ' if ok else 'FAIL'} {info[:70]}")

    print(f"\n[corpus] 本次成功 {ok_n}，失败 {fail_n}。累计成功 {len(done)}，累计失败 {len(failed)}")
    print(f"[corpus] 状态文件: {state}")
    print(f"[corpus] 续跑方式: 重跑同一条命令即可，已完成的会自动跳过")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())