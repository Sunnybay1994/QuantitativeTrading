# M1 HK-HISTORY-R1 HK60 严格多代码可恢复回填主 Agent 阶段验证报告

日期：2026-07-18  
当前结论：**代码与计划验证通过；真实进度 2/8，禁止 finalize/宣称 Gate 通过**

## 1. 实现

新增 `hk_history_backfill.py` 与 `backfill_hk_history.py`，实现不可变 plan、确定 request ID、P1 seed 摘要
绑定、跨进程 3,600 秒 cooldown、联网前 intent/attempt、一次 CLI 最多一个请求、成功响应 raw-first、逐证券
精确 dates 与字段/重复/目标/5,000 截断 Gate、PASS receipt、全批后 finalize 及 existing clean 同键冲突
预检。API 异常只返回脱敏稳定码；不确定 attempt 必须冷却后显式确认。

主审修复了三项首版问题：相对 journal 路径无法进入跨平台锁；首 pending request 的 attempt 状态会被后续
request 覆盖；P1 seed 未绑定 raw/metadata digest。真实 smoke 还发现 P1 seed 包含探针冻结的
`_request_symbol/_market` enrichment，现仅 seed 严格接受并核对这两列，正式 batch raw 仍要求精确 11 个
供应商字段。

## 2. 冻结计划

plan：`artifacts/data_quality/hk_history/hk60_2026-07-10/plan.json`  
SHA-256：`ffbf8f345626b9db834a7b4c31fa8c31a6b60ffe5053ab4953a27bb2c4c50a03`

- 双 Route coverage 逐字段一致：613 STOCK、36,376 个应有键。
- P1 seed：2 只/120 键；`02983.HK`：1 个显式未解决键。
- 剩余 610 只/36,255 键：8 批，大小 `80×7 + 50`；每批预期键数最高 4,800。
- 第一批 request ID：`fba8d6ac9815b523aa0a7bdcbce7558d3da2e65848ae2a3a95f0bf5e6814c13c`，
  80 只、4,800 键、区间 `20260414..20260710`。

## 3. 验证

- WSL/Windows 合并定向回归：85 passed；新模块专项 14 passed。
- WSL/Windows Ruff 通过；WSL mypy 通过。
- 凭据扫描：新代码、测试、任务/报告和 plan 共 6 个目标，token 命中 0。
- 真实 plan 网络前 smoke 正确返回 `HK_HISTORY_COOLDOWN_ACTIVE`；request dirs=0、attempts=0、batch raw
  不存在，仅保留 advisory lock 文件。
- 真实 plan 第一批 4,800 键 fake 端到端 dry-run 通过。
- 全 8 批 fake 演练：8 requests、36,375 个可发布键、60 个 clean 分区、finalize receipt 全部闭合；临时
  数据已清理，未写项目 raw/clean。

第一批于 `2026-07-18T22:26:52.640718+08:00` 执行：唯一网络调用返回并严格通过 80 只/4,800 键，
request ID `fba8d6ac9815b523aa0a7bdcbce7558d3da2e65848ae2a3a95f0bf5e6814c13c`，raw SHA-256
`26942dee1b448d04ecfa007e0ca63838d180289f6a5f8c1c8fa8a7482584f7eb`。metadata/receipt 均为 4,800
行、11 字段，attempt=1、failure=0；attempt 后 clean 修改文件数为 0。

剩余 7 批由 WSL 单写者
`artifacts/data_quality/hk_history/hk60_2026-07-10/run_remaining.sh` 顺序执行；每次启动独立的单请求 CLI，
间隔 3,610 秒，任一非零立即停止，不 retry/切源/finalize。日志：
`artifacts/hk_history_backfill/<plan_sha>/runner.stdout.log` 与 `runner.stderr.log`。

## 4. 剩余风险

- 多代码语法仍是 P1 实测能力，不是 HK 接口文档承诺；任一真实批漂移必须停止整个计划。
- `RawStore.write_request` 单边故障与 `CleanBarStore` 跨分区非原子限制已在任务单披露，不虚称完全自动恢复。
- 真实批次必须逐次间隔至少 3,600 秒；当前仅 2/8，全部 PASS 前不写 clean。

2026-07-18 23:29:39+08:00，后台单写者在 3,610 秒冷却后执行第二批，恰好一次网络请求返回 PASS；
request id `2f7609e959d91a822a80735855345be4cd5f70416d3623ce8eea9a2742451933`。复核为
`receipt=2/attempt=2/failure=0/finalize=0`，随后 runner 进入下一冷却周期。
- 即使 8 批全通过，Tushare source closure 仍明确缺 `02983.HK` 一键；取得合规来源前双 Route HK60 Gate
  不会完全通过。
