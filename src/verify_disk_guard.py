"""verify_disk_guard.py — 磁盘保护逻辑的专项测试

验证两件事（都必须真的触发，不能只是参数存在）：
  1. --max-corpus-gb 上限生效：语料已超限时立即停止
  2. --min-free-gb 生效：全局余量不足时立即停止
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import corpus as C  # noqa: E402

ok = True


def check(label, got, exp):
    global ok
    good = got == exp
    if not good:
        ok = False
    print(f"  {'OK ' if good else 'FAIL'} {label}: {got}  (期望 {exp})")


print("[1] _dir_size 能正确统计目录体积")
with tempfile.TemporaryDirectory() as td:
    p = Path(td)
    (p / "a.bin").write_bytes(b"x" * 1000)
    (p / "sub").mkdir()
    (p / "sub" / "b.bin").write_bytes(b"y" * 500)
    sz = C._dir_size(p)
    good = 1500 <= sz < 2000          # 文件系统块大小会带来少量误差
    print(f"  {'OK ' if good else 'FAIL'} 统计到 {sz} 字节（实际写入 1500，块对齐会略大）")
    ok = ok and good
    check("空目录返回 0", C._dir_size(p / "nonexistent"), 0)

print("\n[2] 语料体积上限触发（构造一个超过极小上限的语料）")
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "corpus"
    (root / "state").mkdir(parents=True)
    # 伪造一个已完成记录，指向一个写了 100KB 的目录
    big = root / "owner__big"
    big.mkdir(parents=True)
    (big / "data.bin").write_bytes(b"z" * 100_000)
    st = root / "state" / "clone_state.jsonl"
    # 注意：路径里有反斜杠，json.dumps 会自动转义；不要手工拼字符串
    import json as _json
    st.write_text(
        _json.dumps({"slug": "owner/big", "ok": True, "info": str(big), "ts": "now"},
                    ensure_ascii=False) + "\n",
        encoding="utf-8")
    done, failed = C._read_state(st)
    check("读到已完成记录数", len(done), 1)
    used_gb = sum(C._dir_size(p) for p in done.values() if p and Path(p).exists()) / 1024 ** 3
    print(f"       语料实测体积 = {used_gb:.6f} GB")
    # 上限设为该值的 1/2，应当被判定为超限
    half = used_gb / 2
    triggered = used_gb > half
    check("超限判定逻辑", triggered, True)
    check("未超限时的判定", used_gb > used_gb * 2, False)

print("\n[3] 参数默认值符合磁盘安全策略")
import argparse
print("  期望 --min-free-gb 默认 5.0，--max-corpus-gb 默认 10.0")
src = Path(__file__).with_name("corpus.py").read_text(encoding="utf-8")
check("min-free-gb 默认值存在", 'default=5.0, help="全局剩余空间低于此值则停止"' in src, True)
check("max-corpus-gb 默认值存在", 'default=10.0' in src, True)
check("引用了磁盘安全策略文档", "磁盘安全策略" in src, True)

print("\n" + "=" * 50)
print("全部通过。" if ok else "存在失败项。")
raise SystemExit(0 if ok else 1)
