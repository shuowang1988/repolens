# RepoLens — 仓库结构相似度检索（PoC 阶段）

目标奖项：**Gemma 4 Developer Agent Paper Track · Best New Resource（$10,000）**

## 为什么选这个题目

主办方在 Best New Resource 说明里**亲自举的例子**有三个：
- 新数据集
- 新工具：「a library which uses Gemma and some other algorithm to **cluster code based on underlying behavior**」
- 新软件：「a **dashboard to explore Github repos that are similar in structure to a target repo**」

**本项目做第三个。** 理由：

1. **主办方点名过**，不需要自己发明"这算不算 Resource"的解释成本。
2. **竞争相对空**——讨论区实测，`code graph 审计`方向已被 dval 占，
   `Graph RAG + GNN` 方向已有人喊话组队，本方向目前无人认领。
3. **不依赖比赛数据再分发**，绕开主办方尚未确认的合规问题。
   输入是公开 GitHub 仓库，与比赛提供的 graph/embedding 无关。
4. **五项评分维度全部能拿到分**（见下表）。

## 五项评分维度怎么拿分

| 维度 | 本项目怎么回应 |
|---|---|
| **Novelty 新颖性** | 现有工具比的是内容相似（README 文本、issue、commit 消息、embedding）；**结构相似度很少被单独定义和度量**。本项目把「仓库结构」显式拆成 5 个可解释分量 |
| **Quality 质量** | 每个分量都有明确定义与可复算的公式，不依赖黑箱 embedding；换任何 Python 仓库都能跑 |
| **Relevance 影响力** | 对**agent 选型**有实际用途：给 agent 找「结构像的参考仓库」来做 few-shot 上下文、迁移工程约定 |
| **Verifiability 可复现** | 纯本地、纯 CPU、断网可跑；附完整代码 + 自检 + 真实仓库演示结果，别人可一键复算 |
| **Clarity 清晰度** | 相似度不只给一个数，每条结果附「为什么像」的自然语言解释 |

## 当前进度

- [x] **特征提取 + 相似度计算层**（`src/repo_structure_similarity.py`）——自检全过，exit=0
- [x] **克隆管理层**（`src/corpus.py`）——19 个仓库实跑通过（64 秒），四个坑已修
- [x] **相似度矩阵运行器**（`src/run_similarity.py`）——真实语料跑通，特征带缓存可续跑
- [x] **失败诊断**（`src/analyze_failures.py` + `src/diagnose_components.py`）——发现并修正了解释文案 bug
- [x] 候选仓库清单（`repos.txt`，19 个：4 目标 + 11 Python 对照 + 4 非语言对照）
- [ ] 看板层（把相似度 + 解释 + 目录树差异可视化）
- [ ] 基线对比：README 文本相似 vs 本方法，找出各自失效的场景
- [ ] 语料扩容（现在 19 个偏少，Writeup 里需要更大的语料支撑）
- [ ] 开源到 GitHub + 写 Writeup

### 本轮实测结果

**批量克隆**：19 个仓库全部成功，64 秒，D 盘仍余 84.9 GB。
```
1/19 .. 18/19  全部 OK   累计成功 19，累计失败 0
```

**真实语料上的相似度**（特征提取 137 秒，其中 django 33.9s、hugo 19.5s、cargo 16.4s 最慢）

fastapi 的 Top-8：
```
1. tiangolo/typer      0.8882
2. encode/uvicorn      0.7829
3. encode/httpx        0.7752
4. django/django       0.7683
5. encode/starlette    0.7597
6. Textualize/textual  0.7513
7. sanic-org/sanic     0.7451
8. python-poetry/poetry 0.7390
```
Go 项目 gin 的 Top-1 只有 **hugo 0.5252** —— 与 Python 项目明显拉开，
说明跨语言判别是有效的（这点会在 Writeup 里作为「方法确实在区分」的第一个证据）。

### ★ 本轮发现的负面结果（这才是这轮最有价值的部分）

**1. 解释文案在说假话 —— 已修**
原 `explain()` 对规模一律输出「代码规模接近」，于是出现了：
```
代码规模接近（1170 vs 84 个代码文件）      ← 差 14 倍
代码规模接近（1170 vs 3049 个代码文件）    ← 差 2.6 倍
```
这在 Clarity 上是硬伤，而且会让读者误以为方法正常。
已改为分级文案（接近 / 同一量级 / 差距较大 / 差距很大）并附实际倍数，
`analyze_failures.py` 自检覆盖了这个 bug。

**2. 分量区分力实测（171 个两两组合）**

| 分量 | 权重 | 最小 | 中位 | 最大 | >0.9 占比 | <0.3 占比 | 判定 |
|---|---|---|---|---|---|---|---|
| size | 0.20 | 0.499 | 0.800 | 1.000 | 0.257 | 0.000 | 有效，但**永远不判负** |
| primary_lang | 0.20 | 0.000 | 1.000 | 1.000 | 0.620 | 0.380 | **二值，中位就顶格** |
| lang_shape | 0.15 | 0.000 | 0.844 | 1.000 | 0.333 | 0.082 | 有效 |
| top_dirs | 0.25 | 0.000 | 0.200 | 1.000 | 0.006 | 0.713 | **稀疏：71% 的组合 <0.3** |
| test_ratio | 0.20 | 0.000 | 0.786 | 1.000 | 0.251 | 0.205 | 有效 |

两个必须诚实披露的问题：
- **`top_dirs` 拿了最高权重 0.25，但 71% 的组合得分 <0.3。**
  真实仓库的顶层目录（`fastapi` 与 `django` 都是 `docs/scripts/tests`，
  但不少项目用 `src/<pkg>`）重合度天然很低。它是「少数拉开差距时的强信号」，
  不是「普遍有效的平滑特征」——原先「top_dirs 权重最高因为它最能预测工程约定」
  这个理由，**在数据上站不住**。
- **`size` 的最小值是 0.499，永远不会低于 0.5。**
  也就是说一个 13000 文件的仓库和 84 文件的仓库，规模分量也还有约 0.5 分。
  这个设计（对数尺度 + `eps` 平滑）在数值上是稳健的，但**语义上是失真的**。

按「区分跨度」等比重分配得到的建议权重（仅作诊断起点，非最优解）：
`size 0.111 / primary_lang 0.222 / lang_shape 0.222 / top_dirs 0.222 / test_ratio 0.222`

> **方法论边界**：本项目**没有标注数据**，所以无法做有监督调权。
> 上面这组数字只是无监督诊断的起点。真正的权重确定需要标注集，
> 这是当前方法的明确局限，会在 Writeup 里写清楚而不是藏起来。

### 下一步优先级

1. **修 `size` 的语义失真 + 给 `top_dirs` 加更合理的处理**（例如把「是否都采用
   `src/` 布局」作为独立布尔特征，而不是只算目录名交集）
2. 语料扩容到 50+ 个仓库，让结论更稳
3. 基线对比（README 文本相似 vs 本方法）
4. 看板层
5. 开源 + Writeup

### 本轮实测结果

单仓库克隆探针（`psf/requests`）：
```
[corpus] 1/1 psf/requests  OK  ...\corpus\psf__requests
续跑：已完成 1，本次待处理 0  → 跳过正确
状态文件损坏（写入 []）→ 已修，不再崩
失败语义：不存在的仓库 FAIL 并记入；重跑默认跳过；--retry-failed 才再试
git 挂起修复后：不存在的仓库 1 秒返回（原先无限等待）
```

## 特征与相似度定义（当前版本）

**5 个特征**
1. 代码文件数（规模）
2. 主导语言（占比最高的语言）
3. 语言分布形状（归一化熵，衡量语言集中还是分散）
4. 顶层目录集合（`src/` `tests/` `docs/` 这类组织方式）
5. 源码:测试 文件数比（测试布局）

**5 个可解释分量**（加权求和）

| 分量 | 权重 | 度量方式 | 「为什么像」的表述 |
|---|---|---|---|
| size | 0.20 | 代码文件数在对数尺度上的接近度 | 代码规模接近 |
| primary_lang | 0.20 | 主语言是否相同 | 主语言同为 X |
| lang_shape | 0.15 | 语言分布熵之差 | 语言集中程度接近 |
| top_dirs | 0.25 | 顶层目录 Jaccard 相似 | 顶层目录重合 |
| test_ratio | 0.20 | src:test 比在对数尺度上的接近度 | 测试目录布局接近 |

> `top_dirs` 权重最高（0.25）是有理由的：**目录布局是仓库「工程约定」最直接的体现**，
> 也最能预测「agent 在这个仓库里会遇到什么样的代码组织」。
> 这个取舍要在 Writeup 里讲清楚——「我们为什么这样加权」本身就是 Quality 的证据。

## 中断与续跑

### 特征层与相似度层（`src/repo_structure_similarity.py`）
无状态，一次跑完，<10 秒。

### 克隆层（`src/corpus.py`）—— 慢且会失败，单独做检查点

```powershell
$py = "C:\Program Files\Python312\python.exe"
Set-Location "D:\Kaggle 比赛\01_gemma4_paper\tool\src"

# 克隆（可反复运行）
& $py corpus.py --list "..\repos.txt" --dest "..\corpus"
```

| | 怎么做 |
|---|---|
| **中断** | Ctrl+C，或直接关进程 |
| **续跑** | 重跑**同一条命令**。读 `corpus/state/clone_state.jsonl`，已完成的自动跳过 |
| **重试失败项** | 默认**不重复重试**失败的仓库（避免限流越陷越深）；要重试加 `--retry-failed` |
| **磁盘保护** | 剩余空间低于 `--min-free-gb`（默认 5GB）自动停止，已完成的保留 |

用 `--depth 1 --single-branch`：结构分析只需要文件树，不需要 git 历史。

### 实测踩过并已修掉的坑（都是这轮真跑出来的）

1. **git 对不存在的仓库会弹凭据提示并无限挂起** —— 不是超时，是**整个流程卡死**。
   修复：克隆时设 `GIT_TERMINAL_PROMPT=0` / `GIT_ASKPASS=` / `GCM_INTERACTIVE=never`，
   让它立刻以非 0 退出码失败。修复后实测：失败仓库 **1 秒**返回。
2. **清单文件的 UTF-8 BOM 会污染仓库名** —— `owner/﻿name` 变成 `https://github.com/﻿owner/name`，
   成功率 0%。修复：读清单用 `utf-8-sig` 并剥掉 BOM。
3. **状态文件里混入非对象行会直接崩** —— `rec.get()` 遇到 `[]` 抛
   `AttributeError: 'list' object has no attribute 'get'`。修复：跳过非 dict 行。
4. **同一 slug 先失败后成功会同时出现在成功表和失败表** —— 导致重复拉取。
   修复：后写的记录完全覆盖先写的（双向清理）。

### 状态文件健壮性测试

```powershell
& $py verify_corpus_state.py    # exit=0
```
覆盖：BOM 开头、末尾半行、非对象行、空文件、文件不存在、双向覆盖、缺 slug 字段。

## 环境

Python 3.12.7，纯标准库（无第三方依赖），断网可跑。