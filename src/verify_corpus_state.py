"""corpus 状态文件健壮性测试：BOM / 半行 / 坏结构 / 重复。"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from corpus import _read_state  # noqa: E402

ok = True


def check(label, got, exp):
    global ok
    good = got == exp
    if not good:
        ok = False
    print(f"  {'OK ' if good else 'FAIL'} {label}: {got}  (期望 {exp})")


with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "clone_state.jsonl"

    print("[1] PowerShell UTF-8 BOM 开头")
    p.write_bytes(
        b"\xef\xbb\xbf"
        + json.dumps({"slug": "psf/requests", "ok": True, "info": "dir"}).encode() + b"\n"
    )
    done, failed = _read_state(p)
    check("成功数", len(done), 1)
    check("失败数", len(failed), 0)

    print("\n[2] 末尾半行")
    p.write_text(json.dumps({"slug": "a/b", "ok": True, "info": "x"}) + "\n"
                  + '{"slug":"c/d","ok":tr', encoding="utf-8")
    done, failed = _read_state(p)
    check("读到成功数", len(done), 1)

    print("\n[3] 行是 JSON 数组而非对象（曾经真实踩到）")
    p.write_text('[]\n{"slug":"a/b","ok":true,"info":"d"}\n[1,2,3]\n', encoding="utf-8")
    done, failed = _read_state(p)
    check("跳过坏结构后成功数", len(done), 1)

    print("\n[4] 空文件与不存在的文件")
    p.write_text("", encoding="utf-8")
    done, failed = _read_state(p)
    check("空文件", (len(done), len(failed)), (0, 0))
    done, failed = _read_state(Path(td) / "nonexistent.jsonl")
    check("文件不存在", (len(done), len(failed)), (0, 0))

    print("\n[5] 后写的记录应完全覆盖先写的（不同时出现在两个表）")
    p.write_text(
        '{"slug":"a/b","ok":false,"info":"timeout"}\n'
        '{"slug":"a/b","ok":true,"info":"/tmp/ab"}\n',
        encoding="utf-8")
    done, failed = _read_state(p)
    check("成功数", len(done), 1)
    check("失败数（后写成功应清掉失败）", len(failed), 0)

    p.write_text(
        '{"slug":"a/b","ok":true,"info":"/tmp/ab"}\n'
        '{"slug":"a/b","ok":false,"info":"timeout"}\n',
        encoding="utf-8")
    done, failed = _read_state(p)
    check("反向：后写失败应清掉成功", (len(done), len(failed)), (0, 1))

    print("\n[6] 缺 slug 字段的记录应被跳过")
    p.write_text('{"ok":true,"info":"x"}\n{"slug":"","ok":true,"info":"y"}\n', encoding="utf-8")
    done, failed = _read_state(p)
    check("有效记录数", (len(done), len(failed)), (0, 0))

print("\n" + "=" * 46)
print("全部通过。" if ok else "存在失败项。")
raise SystemExit(0 if ok else 1)
