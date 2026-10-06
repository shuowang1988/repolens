"""统计语料的语言分布，检查是否均衡。"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from similarity_v2 import RepoFeatures, _top_lang  # noqa: E402

corpus = Path("..") / "corpus"
rows = []
for d in sorted(corpus.iterdir()):
    if not d.is_dir() or d.name == "state":
        continue
    slug = d.name.replace("__", "/")
    n_code = 0
    langs = Counter()
    for f in d.rglob("*"):
        if not f.is_file():
            continue
        if ".git" in f.parts:
            continue
        ext = f.suffix.lower()
        if ext in (".py", ".go", ".rs", ".js", ".ts", ".tsx", ".jsx",
                   ".java", ".cs", ".rb", ".php", ".kt", ".scala", ".swift"):
            n_code += 1
            langs[ext] += 1
    if n_code == 0:
        rows.append((slug, "?", 0, 0))
        continue
    main = langs.most_common(1)[0][0]
    rows.append((slug, main, n_code, len(langs)))

print(f"corpus: {len(rows)} repos\n")
print("language distribution:")
cnt = Counter(r[1] for r in rows)
for lang, n in cnt.most_common():
    bar = "#" * n
    print(f"  {lang:6s} {n:3d}  {bar}")

print("\nper repo:")
for slug, main, n_code, nl in sorted(rows, key=lambda r: (r[1], -r[2])):
    print(f"  {main:6s} {slug:44s} code_files={n_code:6d}")

print("\n" + "=" * 50)
big = [c for c in cnt.values() if c >= 5]
print(f"languages with >=5 repos: {len(big)}")
print(f"max/min ratio among those: "
      f"{max(big)/max(1,min(big)):.2f}" if big else "n/a")
print("VERDICT:", "reasonably balanced" if big and max(big)/max(1, min(big)) <= 2.5
      else "STILL IMBALANCED - cross-language claim is not reproducible yet")