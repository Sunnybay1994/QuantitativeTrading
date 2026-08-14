# M3 G4A 开发示例 FoldPlan 主 Agent 最终验收报告

日期：2026-08-01

结论：**development example 的 G4A 契约在 Windows 原生环境通过；正式 G4 Gate 与 Linux Gate 未关闭。**

## 1. 范围与边界

- 本次只在隔离 worktree 和测试临时目录写入，未修改、重启或读取写入正式 G1 journal、候选目录和发布根。
- development example 固定使用 `release_kind="development_example"`、`formal_gate_eligible=False`、
  `example_id` 和显式 development/example 路径；formal builder 在写入前拒绝 development nominal。
- fixture 扩展为 38 个 history sessions：前 28 个属于 signal window，后 10 个只作 label tail。
- development walk-forward 固定为 train/validation/test/step/embargo=`2/2/2/2/10`，恰好生成两个完整 fold。
- 此报告只证明开发契约可供 G4B 及后续工程工作消费，不代表真实数据性能、正式 G1/G4 或 Linux Gate。

## 2. 实现

- 新增 strict `PlannedFold`、`FoldPlanBuildSpec`、`FoldPlanManifestV1`、formal/development verified artifact。
- 新增 formal/development build、read、verify、supervised-label selector 精确平行 API。
- verifier/selector 通过显式 `FoldPlanUpstreamPaths`、snapshot/provider/experiment specs 和 verified release
  fresh 验真三层上游，不从 root alias 猜公共目录；重叠 alias 按 digest 对应的精确物理路径验真。
- FoldPlan 只读取 verified snapshot calendar 的 signal window；发布完整日期段、两个 embargo label cutoff、
  logical hashes，并拒绝空计划、半折、重叠 test、配置或 identity 漂移。
- fold receipt 精确闭包为 snapshot request/manifest/receipt/calendar 与 experiment manifest/receipt；输出只含
  `folds.json`。formal/development stage 分别为 `folds`/`development-folds`。
- selector 每次消费重新验真 label 与 FoldPlan bundle；旧裸 `TemporalFold` 仅留模块级兼容，不再从包根导出。
- 安全读取复用普通文件、无 hardlink/symlink/reparse、读取期间身份稳定等约束；Parquet 从已验真 bytes 解码，
  避免路径二次打开造成 TOCTOU 窗口。

## 3. 验证证据

Windows 原生 Miniforge：

```text
D:\Miniforge3\python.exe -m ruff check <G4A code/tests>
All checks passed!

D:\Miniforge3\python.exe -m mypy <G4A source/tests>
Success: no issues found in 4 source files

PYTHONPATH=<worktree>/src D:\Miniforge3\python.exe -m pytest
  tests/unit/test_m3_folds.py
  tests/unit/test_m3_development_example.py
  tests/unit/test_m3_label_artifact.py
  tests/unit/test_m3_fold_plan_artifact.py -q
38 passed, 1 skipped

git diff --check
PASS
```

对抗性覆盖包括：formal/development nominal 混用、spec/config 漂移、非规范 JSON、receipt 增项 decoy、
弱 snapshot/experiment receipt 重签、provider dump tool 篡改并重签 receipt/handle、重叠 root alias、
非 session signal 边界、空输出目录/no-clobber、
两折 test 不重叠、tail 不进入 segment、embargo cutoff 选择和无 Qlib/LightGBM/MLflow import。

首次独立初验发现并阻断了三个 P1：上游 receipt 未精确重验、builder/verifier signal 边界分叉、最具体
root alias 被误当公共 base。返工后已统一 signal-date helper，引入显式 upstream paths 和三层 fresh verifier，
并把首次读取的 `folds.json` bytes 直接绑定 receipt output digest；对应反例已加入回归。

复验又发现 provider receipt 可在 dump tool bytes 漂移后被重签的一个 P1。最终实现要求实际 dump tool 同时匹配
配置冻结的 `size_bytes` 与 SHA-256，并新增篡改工具后重签 provider receipt/handle 仍被拒绝的回归。最终独立
复核结论为 PASS（P0=0、P1=0）；仅保留“把工具篡改反例扩展为下游全链重签”的 P2 测试强化建议。

WSL base 定向命令在创建实例前由宿主返回：

```text
Wsl/Service/CreateInstance/E_ACCESSDENIED
```

因此本次没有 Linux 执行结果，Windows 绿测不替代 WSL Gate。

## 4. 正式 G1 同期状态

- PREPARE 已于 2026-08-01 07:05 成功完成。
- Windows PUBLISH 的 `python.exe` PID 6132 在本次低频检查时仍存活并持续累计 CPU，工作集约 12.7 GiB。
- `publish.stdout.log` 与 `publish.stderr.log` 仍为空，尚无成功或失败终态；未对该进程做任何修改或重启。

## 5. 剩余风险与下一步

- WSL 服务权限恢复后，补跑 base 定向 Ruff/mypy/pytest；此前 Linux Gate 保持未通过。
- 正式 G1 PUBLISH 成功后仍需磁盘产物、manifest/receipt/hash、不可变目录及正式 nominal 验收。
- G4B 可立即基于 development FoldPlan 开发 fake/fresh-worker Alpha158 接口，但真实 Qlib、真实数据 coverage、
  性能结论和正式 Gate 必须等待正式 G1 与对应兼容环境验证。
