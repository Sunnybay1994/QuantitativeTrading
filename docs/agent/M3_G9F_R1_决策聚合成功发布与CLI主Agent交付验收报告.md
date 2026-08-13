# M3 G9F R1 决策聚合、成功发布与 CLI 主 Agent 交付验收报告

> 日期：2026-08-13（Asia/Shanghai）  
> 状态：G9F Windows 工程闭环完成；G9G 与 honest 300 真实准入仍开放

## 1. 范围

本包完成 G9A–G9E 结果的固定 G0–G9 聚合、acceptance identity、PASS-only StageRunner 发布和
`acceptance-audit` public CLI。按用户当前指示由主 Agent 串行实现和正常项目验证，没有调用外部 Agent，
也没有用内部 subagent 模拟独立实现或初验。

本包不运行 honest 300 长链、不宣称当前 MLflow 远端或真实 G9 Gate 已通过，也不包含 G9G fake 全链集成。

## 2. 实现结果

- `acceptance.py`
  - `compute_acceptance_key` 绑定 experiment、acceptance config、tracking target、quality receipt、远端观察
    hash 和按计划顺序排列的全部 required receipt hash；
  - `audit_m3_acceptance` 只接 verified subject/plan/quality/config 和只读 tracking verifier，调用 actual
    G9C/G9D/G9E checker，调用者不能传 GateResult；
  - 固定输出 G0–G9 顺序，任一失败形成 FAIL decision；
  - `write_acceptance_candidate` 只对 PASS 向空 temp 写规范 `acceptance_report.json`，FAIL 零文件。
- `acceptance_stage.py`
  - public `audit_formal_m3_acceptance` 和 `run_formal_acceptance_stage` 自行从正式 tracking 模块取得
    MLflow client 与只读 remote verifier；public API 不暴露 `tracking_verifier` 注入；
  - StageRunner 使用全部计划 receipt 作为 ExternalInput，发布
    `acceptance/final/<acceptance_key>/acceptance_report.json` 和严格 ACCEPTANCE receipt；
  - completed resume 重新验真并返回同一 decision/receipt；
  - writer 不从 `quant.research.m3` 包根导出，不能绕过 audit 当作签发入口。
- `run_m3.py`
  - `acceptance-audit --config ... --snapshot-id ...` 已接入真实 public dispatcher；
  - 顺序为 load → resolve → readiness → subject → plan → quality → audit → PASS-only stage；
  - 参数/配置、数据、依赖、本地 stage、tracking、repro、quality/acceptance 分别映射退出码 2–8，多个问题仍由
    `CommandSummary` 取最小非零码；
  - stdout 继续只输出一份规范 JSON，不修改 Git、路线图、远端 run 或上游 artifact。
- `readiness_evidence.py` 新增按当前 config/release 计算唯一 key 后直接定位并 fresh 验真的 resolver；无目录扫描。
- orchestration registry 新增唯一 `acceptance` stage 规格，输出精确一个 `acceptance_report.json`。

## 3. 验证证据

Windows 原生 Miniforge、显式绑定本工作树 `src`：

- G9F core + CLI focused：`54 passed`；
- G9A–G9F acceptance/readiness/quality/CLI 邻接：`92 passed`；
- Ruff（生产与测试定向）：PASS；
- mypy（5 个生产文件）：PASS；
- fresh cold import：`G9F_COLD_IMPORT_PASS`，未加载 MLflow、Qlib 或 LightGBM；
- `git diff --check`：PASS，仅存在工作树既有 LF/CRLF 提示。

pytest 唯一 warning 是工作树 `.pytest_cache` 的 Windows 权限 warning，不影响测试断言或产物。

## 4. 剩余边界

1. G9G 仍需完成 2 folds×2 horizons fake 全链与篡改矩阵；
2. honest 300 首发的 `.writer.lock` 测试口径虽已用小型探针修正，但 completed resume 真实长运行尚未重跑；
3. public acceptance CLI 的真实 PASS 仍依赖当前全部 required receipts、quality artifact 和 MLflow 远端只读观察；
4. Linux/ext4 按用户当前范围暂不实施，本报告不声称平台 Gate。

因此，本报告关闭 G9F 工程包，只解锁 G9G，不关闭 G9 或 M3 总 Gate。
