# M3 G5B R2：正式 PredictionArtifact 返工交付报告

日期：2026-08-09  
角色：G5B R2 返工实现 Agent  
结论：R1 独立复验的三个 P1 已完成最小返工并通过实现者自测，等待未参与本轮返工的全新独立复验

## 1. 返工闭环

### P1-1：两文件写入失败留下半发布目录

- 根因：R1 直接先写最终 Parquet，再写 manifest，第二步失败没有事务回滚。
- 修复：formal 与 development builder 共用 `_write_prediction_bundle`。writer 只登记本次通过
  exclusive create 成功创建的文件及其文件身份；任何写入失败后按 manifest、Parquet 的逆序精确回滚，
  并验证仍是原 output root、非 reparse/link、最终目录为空。
- 失败语义：普通写失败稳定映射为 `M3_PREDICTION_ARTIFACT_INVALID`；若文件身份变化、竞争文件存在、
  unlink 失败或空目录证明失败，则稳定映射为独立的 `M3_PREDICTION_ROLLBACK_FAILED`。两类公开异常均在
  活跃 `except` 外抛出，cause/context 为空。
- 回归：Parquet/manifest 两阶段分别注入 `ValueError` 与 `RuntimeError`，formal/development 均验证
  普通失败后目录为空；另覆盖 unlink 失败时独立 rollback code 且保留不可确认安全删除的文件。

### P1-2：Parquet 非 exclusive，存在 TOCTOU 覆盖

- 根因：R1 的空目录预检与 path-based Parquet writer 之间存在竞态，后者会覆盖并发创建的同名文件。
- 修复：Parquet 与 manifest 均通过 `os.open(O_WRONLY | O_CREAT | O_EXCL | O_BINARY)` 获取已打开的
  binary stream，写入后 `flush` 和 `fsync`；Polars 不再接收最终 path，因此不会覆盖竞争者文件。
- 回归：在空目录预检后分别让竞争者抢占 `predictions.parquet` 和
  `prediction_manifest.json`。builder 均失败，竞争 sentinel 字节保持不变；事务只尝试删除本次创建且
  文件身份仍相同的对象，不删除预存、竞争或未知文件。

### P1-3：copied model root 在拒绝前加载 LightGBM

- 根因：G5A verifier 的 receipt exact closure 位于 `_lightgbm()`/`Booster` 之后。
- 修复：在 `model.py` 内把既有 receipt bytes 验真以及 stage/scope/scope-key/input/output path 精确闭包
  前移到任何 `_lightgbm()` 和 `Booster` 之前；不在 G5B 复制一套预检，也不改变 G5A receipt 合同。
- 回归：构造真实 G5A artifact，复制完整 model root，仍使用原 receipt；对 G5A verifier、G5B builder
  与 G5B verifier 的真实链路注入 hostile `_lightgbm` counter，均在 receipt/root drift 处拒绝且计数为 0，
  G5B output 保持空。

## 2. 改动范围

- `src/quant/research/m3/predictions.py`：共享两文件事务 writer、exclusive stream Parquet/manifest、
  精确身份回滚、空目录证明与独立 rollback 失败语义。
- `src/quant/research/m3/model.py`：将既有 G5A receipt exact closure 前移到 LightGBM load 前。
- `tests/unit/test_m3_formal_prediction_artifact.py`：formal/development 写失败、并发抢占、rollback 失败、
  真实 copied-root pre-LightGBM 对抗回归。
- `tests/unit/test_m3_formal_model_artifact.py`：真实 copied model root + 原 receipt 的 pre-load counter 回归；
  保留经主 Agent 批准的 fresh subprocess delayed-import 断言，不清理 `sys.modules` 掩盖顺序问题。
- 本报告。

未改 contracts/schema、receipt 形态、公开 prediction capability、fresh verification、label-free inference、
predict 精确一次、rank normalizer、正式 G1 artifact/journal 或候选目录。未执行 git add/commit；worktree
中的 G4/G5 既有脏改和无关未跟踪文档均保留。

## 3. 保持不变的 G5B 合同

- builder/verifier 仍 fresh-verify 完整正式 G5A 链，并由公开 G4B inference loader 构造 label-free test
  inference；每个入口仍精确调用 `predict_fitted_model` 一次。
- test keys/order/count、全部 scorable coverage、finite score、唯一 `normalize_prediction_scores`、
  exact 两文件、receipt exact closure、formal/development 类型隔离与异常脱敏保持不变。
- writer 仅改变最终文件的安全创建/回滚机制；成功路径仍由产物实际 bytes 计算 manifest hash 并进入原有
  receipt 闭包。

## 4. 验证证据

测试均使用最小确定 fixture 和独立临时目录；无网络、无 Tushare/BaoStock、未扫描 `data/legacy`，
未写正式 artifact/journal。

### Windows 原生 Miniforge

```text
R2 对抗定向（-k r2）：7 passed, 11 deselected, 113.98s
扩大回归（formal prediction + formal model + development prediction + topk）：
  45 passed, 50328 warnings, 504.78s
Ruff（2 production + 2 formal tests）：PASS
mypy（predictions.py + model.py）：PASS
native LightGBM 路径：由扩大回归覆盖，PASS
```

### WSL Miniforge base（`/mnt/f` DrvFS）

```text
对应扩大回归：45 passed, 50328 warnings, 269.54s
对应 Ruff：PASS
对应 production mypy：PASS
```

warnings 为既有 Pandera/Polars horizontal-concat deprecation；Windows/WSL 另有 worktree
`.pytest_cache` 权限 warning，独立 `--basetemp` 正常完成，不影响结果。

## 5. 未关闭边界

- 本报告仅是 R2 实现与自测证据；必须由未参与本轮返工的全新独立 Agent 复验，通过后再进入主 Agent
  最终验收。
- 未运行正式全 folds/horizons prediction，未证明真实数据规模性能，也未解锁 G6–G9 或宣称 M3 完成。
- WSL 路径是 `/mnt/f` DrvFS，不是 ext4；该 Linux 运行时兼容证据不替代 Linux/ext4 Gate，Windows
  绿测也不替代 WSL Gate。
