# RepoLens — Find repositories that are *structurally* similar

> Given a GitHub repository, find the other repositories whose **code organisation**
> resembles it — not whose text does — and show the reasoning for every result.

[![offline](https://img.shields.io/badge/runs-offline-0a0)][1] [![no-deps](https://img.shields.io/badge/core_deps-stdlib_only-0a0)][2]

[1]: # "Runs fully offline; single-file HTML output"
[2]: # "Core scorer uses only the Python standard library"

---

## Why

When a coding agent lands in an unfamiliar repository, what decides whether it
succeeds is rarely the *topic*. It is the **engineering conventions**: where the
package lives, how tests are laid out, whether the tree is one flat module or a dozen
sub-modules.

"Find a similar repository" tools answer this with **content** — README text, issues,
commit messages, embeddings over source. Those measure *what a project is about*.
None of them reliably measure *how a project is organised*.

We measured the gap. On a 41-repository corpus, the Top-5 lists from README TF-IDF
similarity and from RepoLens overlap by only **0.371**:

| Comparison | Top-5 overlap |
|---|---|
| structural ∩ README TF-IDF | **0.371** |
| structural ∩ filename Jaccard | 0.405 |

The two rankings disagree most of the time.

---

## Quick start

```bash
git clone <this-repo>
cd tool/src

# 1. fetch the corpus (resumable, disk-capped)
python corpus.py --list ../repos.txt --dest ../corpus

# 2. extract features + compute similarities (cached, resumable)
python run_similarity.py --corpus ../corpus \
    --targets tiangolo/fastapi,psf/requests \
    --out ../runs/demo

# 3. build the offline dashboard
python dashboard.py ../runs/demo

# open ../runs/demo/dashboard.html in any browser — no server, no network
```

Self-tests (all should exit 0):

```bash
python repo_structure_similarity.py
python similarity_v2.py
python analyze_failures.py
python verify_corpus_state.py
python verify_disk_guard.py
python verify_dashboard.py
python derive_truth.py                 # recompute every number quoted in the paper
python verify_writeup_structure.py     # re-derive the paper's numbers and compare
```

---

## How it works

Five features, all from the filesystem — **no source-code parsing required**:

| Feature | Definition |
|---|---|
| Code file count | source files, excluding tests / docs / config |
| Primary language | most frequent language |
| Language entropy | normalised entropy of the language distribution |
| Top-level layout | set of top-level directory names |
| Source:test ratio | `(code − tests) / tests` |

Eight interpretable similarity components, combined with explicit weights:

| Component | Weight | Measures |
|---|---|---|
| `size` | 0.18 | ratio-segmented closeness of code-file counts |
| `primary_lang` | 0.12 | dominant language equality |
| `lang_shape` | 0.12 | difference in language entropy |
| `top_dir_count` | 0.18 | log closeness of top-level directory count |
| `flat_single_pkg` | 0.12 | single flat package vs multi-module layout |
| `top_dirs` | 0.12 | Jaccard over top-level directory names |
| `depth` | 0.12 | log closeness of maximum tree depth |
| `test_ratio` | 0.04 | log closeness of source:test ratio |

Every result carries a sentence explaining *why* the two repositories were matched.

---

## What it does **not** do

We measured these rather than assuming them.

**The weights are not supervised.** There is no labelled dataset here. Weights come
from unsupervised diagnostics and explicit design trade-offs; do not read them as
optimal.

**The v1 size term never reached zero.** Its log-smoothed form bottomed out at
**0.304** on our 41-repository corpus, whose code-file counts span 24 to 39,364 (a ratio of
1,640×), so the most extreme size difference still earned about a third of the size credit.
The current piecewise-linear form (full credit within 1.3×, zero beyond 20×) removes that
floor. We report component *distributions* rather than headline numbers for exactly this
reason.

**It complements content retrieval rather than replacing it.** See the 0.371 overlap.

**Language discrimination is emergent, not designed.** Language similarity is one
weighted component among eight. Measured Top-5 same-language counts exceed random
expectation for every sufficiently-sized language class on our corpus (Python 4.80 vs
1.83 expected; Go 3.57 vs 0.85), but that is a property of the *weighted combination* —
no single component guarantees it, and we do not claim it holds on arbitrary corpora.

---

## Design notes

**Why is `primary_lang` only 0.12?** Because raising it damages the structural signal without
achieving reliable language discrimination: an earlier configuration gave it 0.15 and the
effect did not follow the weight. We would rather under-claim than ship a number that looks
meaningful but is not.

**Why piecewise-linear for `size`?** An earlier log-based formulation never scored below
**0.304** on this corpus, so the widest size difference on record still earned roughly a
third of the credit. Numerically stable, semantically wrong. The current form gives full
credit within 1.3× and zero beyond 20×.

**Why are there so many negative results in the writeup?** A tool that reports its own
failure modes with measurements attached is more useful than one that quietly implies
general capability.

---

## Engineering notes

- **Everything is resumable.** Clone layer and feature extraction both checkpoint;
  interrupting and re-running skips completed work.
- **Disk-aware.** The clone layer enforces both a free-space floor and a corpus-size
  ceiling, and stops cleanly rather than filling your disk.
- **BOM-tolerant state files.** A half-written trailing line is skipped, not fatal.
- **ASCII-only shell scripts.** Comments live in the `.md` files, deliberately.

---

## License

MIT. Corpus repositories retain their own upstream licences; RepoLens stores only
derived statistics, never redistributing third-party source.

## Citation

If this is useful in your work, please cite the accompanying Kaggle writeup.
