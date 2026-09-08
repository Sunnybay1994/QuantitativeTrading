# M3 G1-P4B 跨源证据阻塞解除后交付报告

日期：2026-07-14  
角色：外部实现 Agent（非独立初验）  
实际模型标识：`cursor-grok-4.5-high`  
原任务书：[`M3_G1_P4B跨源证据外部闭环任务单.md`](M3_G1_P4B跨源证据外部闭环任务单.md)  
阻塞解除：[`M3_G1_P4B合同阻塞解除与重开任务单.md`](M3_G1_P4B合同阻塞解除与重开任务单.md)  
阻塞历史：[`M3_G1_P4B跨源证据交付报告.md`](M3_G1_P4B跨源证据交付报告.md)（保留，不覆盖）  
状态：**待独立初验/待主验**（不得视为 B4 / G1 / M3 / Gate 通过）

## 1. 范围与边界

本交付在合同阻塞解除后完成 G1-P4B：

1. 从已验收 `G1Candidate` 确定性冻结 30×20=600 样本键；
2. 生成 30 个 BaoStock 单证券请求，严格 journal 获取/恢复 raw；
3. 验证 receipt/raw/frame 闭包；
4. 3000-cell 跨源 reconciliation，输出 detail/summary/issues/身份。

未实现 P4C；未勾选路线图；未宣称 Gate 通过；未联网；未读 token/`_old/`。

## 2. 修改文件清单

| 文件 | 变更 |
|---|---|
| `src/quant/data/m3_g1_candidate.py` | **唯一允许**：`_ISSUE_CODES` 增加 `CROSS_SOURCE_INCOMPLETE`、`CROSS_SOURCE_MISMATCH`；未改 audit |
| `src/quant/data/m3_reference.py` | **新增** P4B 类型、五公共函数、journal/reconciliation |
| `src/quant/data/connectors/baostock.py` | **新增** `fetch_reference_bar_raw` 及参数校验 |
| `src/quant/data/__init__.py` | 仅新增冻结导出 |
| `tests/unit/test_m3_reference.py` | **新增** §8 + 解除任务单 §5 矩阵 |
| `tests/unit/test_baostock_connector.py` | 追加 reference raw 连接器测试 |
| `docs/M3_G1_P4B跨源证据阻塞解除后交付报告.md` | 本报告 |

未修改：`m3_backfill.py`、`storage.py`、Schema、配置、路线图、上游测试。  
原阻塞报告保留为历史证据。

## 3. 冻结接口与行为要点

公共导出：

- `M3ReferenceError`（九稳定码，`from None`，四观察面脱敏）
- `G1CrossSourcePolicy` / `CrossSourceSamplePlan`
- `ReferenceRequestSpec` / `ReferenceRequestPlanV1` / `ReferenceRequestIntentV1`
- `ReferenceRawCandidateV1` / `ReferenceRequestReceipt` / `VerifiedReferenceResponse`
- `CrossSourceFieldStatsV1` / `CrossSourceSummaryV1` / `CrossSourceReconciliationBundle`
- `plan_cross_source_reconciliation` / `plan_baostock_reference_requests` /
  `execute_baostock_reference_plan` / `verify_reference_receipt` / `reconcile_cross_source`

关键不变量：

1. executor 同时接受完整 `sample_plan` 与 `plan`，IO 前从 sample 重建 plan 精确比较；
2. plan-wide preflight 在首个 intent/网络前完成，含 REPLAY receipt 全闭包；
3. journal：exclusive temp + file fsync + `os.link` no-clobber + parent dir fsync；生产路径无
   `os.replace`/`os.rename`；
4. 有效 receipt 零网络复用；candidate 恢复；intent-only 网络续跑；网络失败保留 intent；
5. reconciliation：3000 守恒；INCOMPLETE 任意缺行；MISMATCH 仅当 mismatch_rate **严格大于** 阈值；
6. `G1QualityIssue` 跨源码可构造；`audit_g1_candidate` 仍只产出主源码。

## 4. 任务书逐项映射（摘要）

| 项 | 证据 |
|---|---|
| §1 四件事 | `m3_reference.py` 五公共函数 + connector |
| §2 允许文件 | 上表；`_ISSUE_CODES` 仅两跨源码扩展 |
| §3 executor 签名 | `execute_baostock_reference_plan(sample_plan=..., plan=...)` |
| §4 类型/五函数/错误码 | 包根导出；九码 `M3ReferenceError` |
| §5 身份自证 | dataclass `__post_init__` 重算 hash/闭包 |
| §6 connector+journal | `fetch_reference_bar_raw`；preflight/状态机测试 |
| §7 reconciliation | 3000-cell、两类 issue、严格阈值 |
| §8 必测矩阵 | `test_m3_reference.py` + connector 追加 |
| 解除 §5 | 跨源码构造、未知码拒绝、audit 主源码不变、阈值边界 |

## 5. 实现者自测覆盖

`tests/unit/test_m3_reference.py`（91）覆盖任务书 §8 与解除任务单 §5，含：

- policy 边界/非法；audit 失败；不足 30/20；hash 顺序；
- plan/request 漂移与 sample-hash-only 无法绕过；
- connector 调用次数/参数/logout/重复行/脱敏；
- 第 30 目录冲突 plan-wide 零增量；symlink/FIFO/未知文件；
- journal 首次/重跑/恢复/intent-only/网络中断/漂移/fsync 路径；静态无 replace/rename；
- 严格 JSON、路径逃逸、receipt 多层漂移、0/5999/6000；
- 30×20 稳定、extra dates、停牌 0、错误 code/date/adjustflag；
- atol/rtol、volume、等于/略超阈值、缺行=5、3000 守恒、两类 issue；
- bundle 漂移与 wholesale 须由 `reconcile_cross_source` 重执行发现；
- pure planners/reconcile 零 IO/网络。

`test_baostock_connector.py` 追加 reference raw 精确参数、去内部列、非法参数、登录失败不 logout。

## 6. 验证结果（WSL Miniforge `base`）

全部经 `wsl.exe` → `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，
`/home/mabw/miniforge3/bin/conda run -n base`。禁止 Windows Python。

| 命令 | 结果 |
|---|---|
| 定向 `pytest -q tests/unit/test_m3_reference.py tests/unit/test_baostock_connector.py` | **110 passed**（约 3 min） |
| 全量 `pytest -q` | **746 passed**（约 8–9 min；既有 Pandera/Polars deprecation warnings） |
| `ruff check src tests` | **All checks passed** |
| `mypy src` | **78 source files，0 issues** |

本轮未联网、未读 token、未访问 `_old/`、未写 release。

## 7. 已知限制

- 未实现 P4C reader/manifest/immutable release；不得开始下游包；
- 默认测试全部 fake BaoStock / 临时 RawStore；真实 BaoStock smoke 不在本包；
- 夹具为扩展 history 的 300 成分 candidate（module scope）；全量耗时主要来自 P4A/P4B 夹具重建；
- 不宣称价格完备、B4/G1 Gate 或 M3 通过。

## 8. 交付声明

实现与自测完成，状态：**待独立初验/待主验**。  
请未参与本实现的外部会话按原任务书独立初验矩阵验证；初验通过后方可交主 Agent 终验。  
不宣称 B4 / G1 / M3 / 任一 Gate 通过。
