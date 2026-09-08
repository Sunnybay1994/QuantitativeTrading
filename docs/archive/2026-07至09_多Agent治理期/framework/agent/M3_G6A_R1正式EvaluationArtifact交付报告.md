# M3 G6A R1：正式 EvaluationArtifact 实现交付报告

日期：2026-08-09  
角色：实现 Agent  
状态：**实现与自测完成，等待独立初验；不得据此宣布 G6A Gate 通过**

## 1. 改动范围

- `src/quant/research/m3/evaluate.py`
  - 新增正式 `build_evaluation_artifact` / `verify_evaluation_artifact`；
  - 接入 exact formal capability gate、G1→G5B prediction fresh verifier 与独立 label fresh verifier；
  - 从正式 G1 eligible、G4B test、G5B prediction、G3A label 重建五层 key/count/coverage；
  - 复用既有八状态、Pearson/Spearman average-rank、sample-std ICIR 数学 helper；
  - 复用 `_artifact_publication.py` 的目录实体锚、租约、exclusive-create、三文件事务与精确 rollback；
  - 新增 formal exact 17-input/3-output receipt 物理路径闭包和 wholesale 重算验证。
- `src/quant/research/m3/__init__.py`
  - 安全导出两个 formal G6A 入口；既有 G4/G5 formal 导出属于本工作树上游已验收内容，本任务未改其行为。
- `tests/unit/test_m3_formal_evaluation_artifact.py`
  - 新增正式闭环、17-input receipt、类型/路径混配、receipt 多输入、整包重签篡改、三 writer rollback、hostile 脱敏、八状态优先级、tie 与 ICIR 手算测试。

未修改 `contracts.py`、development capability、G1–G5B 生产实现、配置或正式 artifacts/journal；未联网、未扫描
`data/legacy`、未执行 add/commit。

## 2. fresh call 图与身份闭包

```text
build/verify_evaluation_artifact
  -> exact formal input/spec/path gate
  -> verify_prediction_artifact
       -> 既有正式 G5B 链继续 fresh G5A/G4C/G4B/G3/G2/G1
  -> exact 比对 fresh prediction（root/frame/manifest/receipt）
  -> verify_label_artifact
       -> 重算当前 horizon labels/diagnostics 并 fresh G1/snapshot/experiment
  -> exact 比对 fresh label（root/frames/manifest/receipt）
  -> 再次检查跨 capability identity 与嵌套 receipt 物理路径
  -> 重建五层、逐日数学、汇总、manifest
```

builder 在调用 fresh verifier 前已通过 `ArtifactPublication` 锚定 caller-created 空目录；全部 fresh、数学、identity、
count 和内存 bytes 完成后才写首个最终文件。verifier 重新执行相同 fresh/重算路径，不信任 evaluation 三文件的内部
自洽或 receipt 重签。

## 3. 五层、四分母与八状态

| 层 | 本次唯一来源 | 约束 |
|---|---|---|
| eligible | formal G1 `eligible_keys.parquet` ∩ 完整 test dates | logical keys hash 必须等于 fresh G5B eligibility |
| scorable | fresh G4B `test.parquet` selected feature 非全缺失行 | `scorable ⊆ eligible` |
| predicted | fresh G5B `(as_of,symbol,score)` | `predicted == scorable` |
| labeled | fresh G3A 当前 horizon 的成功 labels | `labeled ⊆ eligible` |
| evaluated | predicted ∩ labeled | 只用于 IC，不反向筛 prediction |

四个 coverage 分别按 `scorable/eligible`、`predicted/scorable`、`labeled/eligible`、
`evaluated/labeled` 重算；分母 0 为 null，汇总按总 count 而不是 daily ratio 平均。

定向测试逐日覆盖固定优先级的八个状态，并额外保留两个 `COMPUTABLE` 日。受控 tie 的 Pearson/Spearman 均为
`sqrt(3)/2`；两日 ICIR 用 `mean / sample_std(ddof=1)` 手算对照，单日和 zero sample std 均为 null。

## 4. 17-input / 3-output receipt

formal receipt 精确要求 `stage=evaluation`、`scope=WORK`、`scope_key=spec.work_key`。输入依次覆盖：

1. G1 release manifest、eligible keys；
2. G4B feature manifest、receipt、coverage、test；
3. G5B prediction manifest、receipt、predictions；
4. G3A label manifest、receipt、labels、diagnostics；
5. fold manifest、receipt；
6. experiment manifest、从 nested `FoldPlanUpstreamPaths` 唯一导出的 receipt。

实现要求 17 个 normalized absolute path 唯一，并逐对拒绝同一物理文件别名；显式 feature/fold/label receipt 与
prediction→model→alignment→feature/fold 嵌套链必须指向同一 exact 路径。通用 receipt verifier 重读全部 bytes，
G6A 再检查 stage/scope/key 和 exact paths。输出只允许三个 evaluation 文件。

## 5. 发布事务与失败语义

- formal 三文件均先在内存生成，再经同一个 `ArtifactPublication` 独占流写入、flush/fsync、readback、commit；
- 任一 writer 或 readback/commit 失败只回滚本调用拥有且身份仍一致的文件；
- rollback 无法证明时稳定码为 `M3_EVALUATION_ROLLBACK_FAILED`；其他 formal 边界失败统一为
  `M3_EVALUATION_ARTIFACT_INVALID`；
- 测试分别在 Parquet、metrics JSON、manifest JSON writer 抛 hostile 非 ValueError，均证明目录回到空、
  `cause/context is None` 且私有 sentinel 不外泄。

## 6. 验证结果

Windows 原生 Miniforge：

- 任务书四文件 pytest：`49 passed`，467.15 秒；
- Ruff（`evaluate.py`、`__init__.py`、formal test）：PASS；
- mypy `evaluate.py --no-incremental`：PASS；
- development evaluation 单独回归：`31 passed`（命令在测试完成后因 180 秒外层 timeout 返回 124，pytest 已完整
  输出 31/31 PASS；最终四文件组又包含并通过同一测试）。

WSL Miniforge base，`/mnt/f` DrvFS：

- 对应四文件 pytest：`49 passed`，216.31 秒；
- Ruff：PASS；
- mypy `--no-incremental`：PASS。

warning 仅为既有 Pandera/Polars deprecation 和工作树 `.pytest_cache` 无写权限；每次 pytest 的实际临时目录均使用
独立 `--basetemp`。`git diff --check` 对本任务白名单 PASS。

## 7. 未关闭边界

- 本交付只是实现者自测，仍需未参与实现的独立 Agent 增加对抗反例并 PASS，再由主 Agent 终验；
- 测试 formal 链复用 G4/G5 的确定 fixture 和 fake LightGBM worker，不是正式全 folds/horizons work 或真实性能证据；
- 当前 WSL 路径为 `/mnt/f` DrvFS，不是 ext4，不能关闭 Linux/ext4 Gate；
- 未执行正式 evaluation work，未进入 G6B，也未宣称 G6A、M3 或真实 acceptance threshold 完成。
