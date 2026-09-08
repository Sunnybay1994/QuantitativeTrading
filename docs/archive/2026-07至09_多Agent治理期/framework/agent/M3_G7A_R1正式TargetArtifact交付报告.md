# M3 G7A R1：正式 TargetArtifact 交付报告

日期：2026-08-09  
状态：实现与双平台定向自测完成；待独立初验和主 Agent 最终验收

## 1. 交付范围

- 在 `quant.research.m3.targets` 新增冻结签名的 `build_target_artifact` 与
  `verify_target_artifact`，并从安全包根导出。
- builder/verifier 各自精确调用一次正式 `verify_prediction_artifact`，再精确调用一次公开
  `build_inference_segment`；fresh prediction 必须与调用方 capability 的绝对 root、DataFrame、manifest、
  manifest hash 和 receipt hash 全相等。
- 从正式 G1 `eligible_keys.parquet` 取得完整 test-date eligible domain；scorable 只来自 label-free inference
  loader。G7A 没有直接读取 label、账户、持仓、现金或 G7B+ 产物。
- 新增 formal 测试；未修改 `contracts.py`、development schema/receipt、G1--G6 实现或正式 artifact/journal。

## 2. 数学与身份闭包

- `TargetBuildSpec` 由 prediction identity 与 scientific config 的 `portfolio/features` selector 精确重建；
  formal capability 和所有 spec/path dataclass 均要求 exact type。
- test dates、eligible、scorable、prediction 三层逐日闭包；`scorable ⊆ eligible`、
  `prediction keys = scorable keys`。缺/多/重复/乱序/区间外 prediction、空 eligible/prediction、低 coverage
  均 fail closed。
- prediction 保持 G5B 唯一 normalizer 的 `as_of,rank` 物理顺序，Top-k 直接消费已验真 rank，不按 symbol
  重排 prediction。target 输出按 `as_of,symbol` 完整覆盖所有 eligible，未选和 unscorable 行显式为零。
- 权重用 `Decimal(str(...))` 计算
  `min((1-cash_buffer)/n_selected,max_weight)` 后投影 Float64；manifest 的 `n_selected` 是逐日选择数之和。

## 3. 发布、receipt 与错误语义

- 复用共享 `ArtifactPublication`：调用方已存在空目录、root 实体 lease、首个内容字节前 current-root 复验、
  三文件 exclusive create、owned-identity readback、exact tree、逆序精确回滚和 no-clobber。
- 输出精确为 `target_weights.parquet`、`target_daily.parquet`、`target_manifest.json`；Parquet 参数、canonical
  JSON、row-key hash 与 development 公共协议一致。
- receipt 固定 `targets/WORK/spec.work_key`，精确 14 个唯一、无 alias 输入：G1 manifest/receipt/eligible，
  feature manifest/receipt/coverage/test，prediction manifest/receipt/parquet，fold manifest/receipt，experiment
  manifest/receipt；输出精确三文件。
- 普通失败稳定为 `M3_TARGET_ARTIFACT_INVALID`；共享 publication 无法证明回滚时为
  `M3_TARGET_ROLLBACK_FAILED`。两者不泄露路径、token、底层异常链或数据内容。

## 4. 验证证据

Windows 原生 Miniforge：

- formal G7A：`5 passed`，93.44 秒；覆盖正式闭环、14/3 receipt、完整域和 Decimal、缺/多/重复/乱序/日期
  反例、copied receipt、unknown input、hostile fresh/writer 脱敏回滚及 root replacement 首字节前拒绝。
- development 直接受影响数学/闭环/轻导入节点：`6 passed`，33.29 秒。
- Ruff：实现、包根和 formal 测试 `All checks passed`。
- mypy：两个生产文件 `Success: no issues found`。
- 包根轻依赖探针：`G7A_LIGHT_IMPORT_PASS`，未加载 LightGBM/Qlib/MLflow。

WSL Miniforge `base`（`/mnt/f`）：

- 同一 formal 5 节点及 development 6 节点：`11 passed`，52.53 秒。
- Ruff 与 mypy 均通过；上述 11 节点包含包根轻依赖断言。
- `stat -f -c %T .` 返回 `wslfs`，因此这是 WSL/DrvFS 兼容性验证，不是 ext4/Linux Gate。

补充：一次包含完整 G5B 的 Windows 合跑在 424 秒命令预算耗尽，另一次完整 development target 套件在
304 秒预算耗尽；二者均无失败摘要，且残留 pytest 已精确检查/清理。按任务要求改用本包 formal 全套和直接受
影响 development 节点得到上述确定结果，不把超时记作通过。

## 5. 未关闭边界

- 当前只是 G7A 工程合同自测完成，尚未经过独立初验和主 Agent 最终验收，未解锁 G7B。
- 未运行真实 G1 全折 target、真实数据性能、正式 M3/M4 Gate 或 Linux/ext4 Gate。
