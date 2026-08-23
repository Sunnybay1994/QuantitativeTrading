# M3 G6A development example 逐 Work 评价 Artifact 阶段验收

日期：2026-08-02
信任域：`development_example`（`formal_gate_eligible=false`）

## 结论

G6A 的 development example 工程合同已实现并通过 Windows 与 WSL base 定向验证。该结论只证明隔离
示例链能从 fresh-verified G5B prediction 及其完整上游，生成并重新验证逐 work 的 evaluation artifact；
不代表 production G6、真实数据绩效或 Linux/ext4 Gate 已关闭。

## 冻结边界与实现

- 输出严格为 `daily_ic.parquet`、`metrics.json`、`evaluation_manifest.json`，writer 只接受已存在的空目录；
- 每个 test date 重建 eligible、scorable、predicted、labeled、evaluated 五层唯一 key，并强制
  `scorable ⊆ eligible`、`predicted = scorable`、`labeled ⊆ eligible`、
  `evaluated = predicted ∩ labeled`；
- 逐日记录五层计数与四类 coverage，分母为零写 `null`；汇总 coverage 由总计数重新相除，不平均逐日比率；
- IC 状态按冻结的八状态优先级唯一归类；Pearson/Spearman 只在满足最小样本且双方非零方差时计算，
  Spearman 使用 average ties，单个可计算日的 ICIR 为 `null`；
- manifest 绑定 experiment/work、prediction/label/feature/fold、eligible keys、test dates、scientific config
  及三个输出的内容哈希；JSON canonical 且禁止非有限值；
- verifier 先 fresh-verify G5B 及其完整上游，再重算 daily/metrics/manifest，并精确核对
  `development-evaluation` WORK receipt 的 10 个输入与 3 个输出；底层 parquet/JSON/IO 异常统一 fail-closed；
- development capability 固定为 `development_example` 与 `formal_gate_eligible=false`，不会生成或冒充
  `VerifiedEvaluationArtifact`。

## 对抗覆盖

测试覆盖八种状态、四个 denominator、五层集合破坏、minimum 边界、average ties、零方差、单日 ICIR、
汇总 coverage、no-clobber、identity 漂移、parquet/metrics/manifest/receipt 篡改、非 int/NaN JSON、整包跨
work 替换，以及核心 import 不加载 Qlib、LightGBM 或 MLflow。

## 验证证据

Windows 原生 Miniforge：

```text
PYTHONPATH=<worktree>/src D:\Miniforge3\python.exe -m pytest \
  tests/unit/test_m3_evaluation_artifact.py -q
19 passed

D:\Miniforge3\python.exe -m ruff check <G6A files and test>
All checks passed

D:\Miniforge3\python.exe -m mypy <G6A source files>
Success: no issues found
```

WSL Miniforge `base`（同一隔离 worktree）：

```text
PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base python -m pytest \
  tests/unit/test_m3_evaluation_artifact.py -q
19 passed in 78.47s
```

两平台均出现既有 Pandera/Polars `horizontal` 默认行为弃用警告，不影响断言。

## 尚未关闭

- production G4–G6 对正式 G2/G3 artifacts 的全链构建与发布；
- G6B 跨折 summary、G7 统一回测、G8 复现/追踪与 G9 Gate；
- 正式数据的覆盖、IC/ICIR、性能结论，以及 Linux/ext4 Gate。
