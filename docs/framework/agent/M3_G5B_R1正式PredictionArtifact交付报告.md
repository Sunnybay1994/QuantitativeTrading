# M3 G5B R1：正式 PredictionArtifact 交付报告

日期：2026-08-09  
角色：G5B R1 实现 Agent  
结论：实现与自测完成，等待未参与实现的全新独立初验

## 1. 改动范围

- `src/quant/research/m3/predictions.py`
  - 新增正式 `build_prediction_artifact` / `verify_prediction_artifact`；
  - builder/verifier 均 fresh-verify 正式 G5A model，并通过正式
    `build_inference_segment` fresh-load G4B label-free test inference；
  - exact type/spec/path/root、test keys/order/count、唯一 normalizer、manifest、
    receipt 和 no-clobber 闭包；
  - formal 边界统一脱敏为 `M3_PREDICTION_ARTIFACT_INVALID`，不保留 cause/context；
  - development 入口、stage 和 capability 保持独立。
- `src/quant/research/m3/__init__.py`
  - 安全导出两个正式入口；不在包根加载 LightGBM。
- `tests/unit/test_m3_formal_prediction_artifact.py`
  - 新增完整 formal 闭环、predict 调用计数、copied-root、key/order、non-finite、
    subclass、hostile exception、no-clobber、exact receipt、同 work score 重签篡改，
    以及真实 native LightGBM public-predict smoke。
- `tests/unit/test_m3_formal_model_artifact.py`
  - 经主 Agent 明确批准的单一白名单补充：将 delayed-import 从当前 pytest 进程断言
    改为 fresh subprocess 断言，与已验收的 development G5A 测试模式一致；不改变 G5A
    生产代码或模型合同。
- 本报告。

未修改 `contracts.py`、domain schema、model/alignment/features 生产逻辑、development tests、
配置、正式 G1 artifact/journal 或候选目录；未执行 git add/commit。worktree 中其余既有脏改均保留。

## 2. Fresh call 图与 label-free 边界

builder 和 verifier 各自执行：

```text
exact formal inputs/spec/path identity
  -> verify_model_artifact(
       model.root + model receipt + ModelUpstreamPaths + 完整 G1→G4C/G5A 参数
     )
  -> fresh return exact-equals caller VerifiedModelArtifact
  -> build_inference_segment(
       feature + folds + InferenceUpstreamPaths + 正式 G1→G4B 参数
     )
  -> exact test metadata/MultiIndex/scorable keys/order/count
  -> predict_fitted_model(exact model, inference)  # 本入口精确一次
  -> normalize_prediction_scores                  # 唯一 normalizer
  -> manifest / output 或逐行重构验证
```

formal inference 调用不包含 label、label spec、horizon label 或 cutoff。label/alignment 只存在于
历史训练模型的 G5A fresh closure；test keys 唯一来自 fresh G4B test scorable rows。builder 与
verifier 的测试计数均证明每次入口 `verify_model=1`、`build_inference_segment=1`、
`predict_fitted_model=1`。copied model root、反序 inference keys 和 hostile upstream 均在
G5B predict 0 次、output 0 bytes 前失败。

## 3. 预测、manifest 与 receipt 闭包

- inference metadata 必须为 exact `as_of: Date, symbol: String`，唯一严格递增，并与 exact
  `("as_of", "symbol")` pandas MultiIndex 逐行同序；不得排序、去重、补行或裁成有 label 子集。
- expected keys 从 fresh formal feature test 全部 scorable rows 重建，且全部位于 planned fold
  test dates；`n_predicted == n_scorable > 0`、`n_scorable <= n_eligible`。
- score 数量精确匹配且 finite；只调用现有 `normalize_prediction_scores`。产物保持其稳定
  `score DESC, symbol ASC` rank 顺序，prediction logical key hash 按最终 Schema 行序计算。
- 输出精确为 `predictions.parquet`、`prediction_manifest.json`；空实体目录、junction/reparse、
  第二次 build 和额外/缺失输出均 fail closed。
- `stage=predictions`、`scope=WORK`、`scope_key=work_key`；receipt 精确 8 inputs / 2 outputs：
  model metadata + receipt、feature manifest + receipt、fold manifest + receipt、experiment manifest、
  alignment receipt。路径缺失、多余、重复、alias 或错误 root 均失败。
- 同 work 修改全部 score、重写 parquet/manifest hashes 并对 exact inputs/outputs 重签 receipt，
  verifier 仍通过 fresh predict 的逐行重构拒绝。

## 4. 验证证据

所有自动测试使用独立临时目录，无网络、不扫描 `data/legacy`，未写正式 artifact/journal。

### Windows 原生 Miniforge

```text
formal G5B 单文件：5 passed, 6435 warnings, 71.13s
任务书扩大组（formal prediction + formal model + development prediction + topk）：
  38 passed, 38920 warnings, 406.89s
Ruff（prediction production/export + formal prediction/model tests）：PASS
mypy（src/quant/research/m3/predictions.py）：PASS
native LightGBM save/load + public predict_fitted_model：PASS
```

扩大组首轮为 `37 passed, 1 failed`：G5B native smoke 先加载 LightGBM 后，既有 G5A formal
delayed-import 测试仍读取共享进程 `sys.modules`。根因是测试顺序耦合，不是生产 import 回归。
按主 Agent 裁定，将该 G5A 测试改为 fresh subprocess；原失败顺序先定向 `2 passed`，随后完整
同序扩大组得到上述 `38 passed`。未通过清理 `sys.modules` 掩盖问题。

### WSL Miniforge base（`/mnt/f` DrvFS）

```text
对应 4-file pytest：38 passed, 38920 warnings, 221.45s
对应 Ruff：PASS
对应 production mypy：PASS
```

warnings 为既有 Pandera/Polars horizontal-concat deprecation；Windows/WSL 另各有 worktree
`.pytest_cache` 权限 warning，不影响独立 basetemp 测试结果。本轮创建的 `.pytest-g5b-*`
Windows 临时目录已清理；WSL basetemp 位于 `/tmp`。

## 5. 未关闭边界

- 当前 PASS 是 G5B 实现者自测证据，仍须未参与实现的全新独立初验和主 Agent 最终验收；
- 未运行正式全 folds/horizons prediction work，未证明真实数据性能、G6–G9 或 M3 完成；
- WSL `/mnt/f` 是 DrvFS，本结果不替代 Linux/ext4 Gate；Windows 绿测也不替代 WSL Gate；
- formal 正例的完整来源闭包使用最小确定 fixture；native smoke 真实调用已保存 LightGBM 模型，
  但不代表正式大数据训练/推理性能结论。
