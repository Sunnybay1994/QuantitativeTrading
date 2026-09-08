# M3 G7F R4：pre-final Release/Context 实体绑定返工交付报告

日期：2026-08-10  
角色：外部实现 Agent（全新会话）  
状态：**实现者交付与双平台自测完成，待未参与实现的全新独立初验**  
环境：Windows 原生 Miniforge 定向；WSL Miniforge `base`（DrvFS `/mnt/f` 与 `/home/mabw/AI_Coding_win/...` 同树）兼容；默认不联网

任务单：[`M3_G7F_R1正式A股三场景回测Artifact任务单.md`](M3_G7F_R1正式A股三场景回测Artifact任务单.md) §18  
前置：[`M3_G7F_R3_正式G1Quality来源闭包与路径类型分离独立复验报告.md`](M3_G7F_R3_正式G1Quality来源闭包与路径类型分离独立复验报告.md) 主验补充 S1/S2 FAIL

## 1. 交付结论

按 §18 最小返工：`BacktestArtifactFreshVerificationContext` 新增 exact `release: VerifiedG1Release`，构造时递归验 nested `G1Release` / `G1ManifestV5` / `G1QualityReportV1` / 17 项 artifact paths，并捕获 root/manifest/quality/八表私有实体 snapshot（`init=False/repr=False/compare=False`）。所有 formal 入口在 29 输出读取 / G7E 回放前先：递归 exact 验 caller release、与 `fresh_context.release` 逐字段相等、重算并比对构造时 snapshot，再走原有闭包。

关闭同 fresh context 下 S1（nested SimpleNamespace）、S2（exact copied-root `VerifiedG1Release`）、同路径换 inode、context `release`/`_source_snapshot` 漂移；合法 build→pre-final→receipt→final 仍通过。`dataclasses.replace` 会经 `__post_init__` 重建新 context（新验证请求），不在本包声明跨请求持久来源证明。

本报告只声明实现者交付与自测完成，**不**声明独立初验、主验、G7F/G8/ext4/M3 Gate PASS。G8 继续暂停。

## 2. 关键实现

- `BacktestArtifactFreshVerificationContext.release` + 私有 `_source_snapshot`
- `_require_formal_g1_release_exact` / `_capture_formal_g1_source_snapshot` / `_validate_formal_release_context_binding`
- `_validate_formal_input_identity` 入口先绑定重验
- development API、21/29 数量、metrics、publication、稳定错误码未改；未改 G1/G7A/B/E/P0/G8
- `__init__.py` 无需新增导出（类型已安全导出）

## 3. 测试覆盖

- fixture 构造 context 时绑定同一 `release`
- 正式 S1/S2、同路径换 inode、context release/snapshot 漂移、合法闭环
- 既有 R3 quality 闭包 / 三次 G7E / Decimal / 29-file / golden 保持

## 4. 验证证据（终验串行；targeted 不重复）

### Windows

| 项 | 结果 |
|---|---|
| targeted R4（本轮前已确认，未重跑） | `1 passed`，394.11s |
| Ruff / mypy（本轮前已确认） | All checks passed / Success |
| G7F unit+golden | `12 passed`，1114.94s |
| 邻接（排除 G8） | `128 passed`，720.65s |
| R2 fixed-order | `4 passed`，158.08s |
| cold / scoped diff-check | `cold-ok` / `diff-check-ok` |

### WSL base（DrvFS 兼容，非 ext4 Gate）

| 项 | 结果 |
|---|---|
| G7F unit+golden | `12 passed`，921.66s |
| 同构邻接 | `128 passed`，436.42s |
| R2 fixed-order | `4 passed`，129.16s |
| Ruff / mypy / cold | 通过 / Success / `cold-ok` |
| diff-check | WSL worktree git 路径无效；以 Windows scoped `diff-check-ok` 为准 |

警告仅为既有 Pandera/Polars deprecation 与 `.pytest_cache` 无写权限，不改变结果。

## 5. 文件范围

1. `src/quant/backtest/a_share_reporting.py`
2. `tests/unit/test_m3_g7f_formal_backtest_artifact.py`
3. 本任务单状态
4. 本交付报告

未修改 G8/G1/G7A/B/E/P0、development reporting、contracts、schemas、config；未联网、add、commit。终验后清理本轮 `.tmp-g7f-r4-*`。

## 6. 剩余风险与下一步

- G8 仍因旧 formal context 缺 `release` 字段而需后续同步；R4 主验 PASS 前不得解锁。
- 私有 snapshot 含平台 inode，不得进入 portable manifest/receipt/hash；当前仅 process-local。
- WSL 证据在 DrvFS，不能表述为 Linux/ext4 Gate。
- 下一步：未参与本轮实现的全新外部 Agent 只写
  `docs/agent/M3_G7F_R4_preFinalReleaseContext实体绑定独立复验报告.md`，并增加未用反例。
