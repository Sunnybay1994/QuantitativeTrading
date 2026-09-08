# M3 G7F R1：正式 A 股三场景回测 Artifact 交付报告

日期：2026-08-10
状态：**实现者交付与双平台自测完成，待未参与实现的全新独立上下文初验**

## 1. 交付结论

已按任务单实现正式 G7F 三场景回测 Artifact。Production builder/verifier 从 fresh target、plan、experiment、
G1 release 与 config 开始，直接调用 public plan verifier 和 F0 loader，并以同一份 facts、相同初始现金和基础
成本日程按固定 `0.5/1/2` 顺序实际调用 G7E 三次。每个场景输出七表、metrics 和 scenario manifest，根目录
输出 bundle metrics/manifest；29 个文件由 P0 whole-root nested transaction 一次提交，verifier fresh 重算并执行
whole-tree/receipt 复验。

本报告只声明实现者交付和自测完成，不声明独立初验、主验、G7F、完整 G7 或 M3 Gate PASS。

## 2. 关键实现

- fresh 边界 exact 校验 outer 与 nested identity/path，G7F import 的 public plan verifier、F0 loader 各调用一次；
- actual G7E 独立运行三次，不接受 caller result、fill、transition、schedule、frame、multiplier 或 metrics；
- 全部经济指标在固定 80 位、`ROUND_HALF_UP` 私有 Decimal context 中计算，最后单向投影 Float64；
- benchmark 唯一接受 config/F0 的 `510300.SH` raw bars；turnover 保持 gross/2，rejection count 按唯一 intent；
- terminal exit 使用 base 1× sell slippage、向下 tick、实际 execution notional 和逐分项费用；
- scenario cost hash 只缩 commission rate/min/slippage，stamp tax 和 transfer fee 保持基础值；
- 精确生成 29 outputs，并验证 scenario manifest 的 8 个自排除 entries 与 root manifest；
- receipt 严格绑定 21 inputs/29 outputs，拒绝额外、缺失、替换、漂移和非普通物理实体；
- P0 lease 覆盖 fresh、三次回放、序列化、readback 与 commit，保持 no-clobber/owned-only rollback。

## 3. 首轮缺陷与修复

新增 hostile/P0 no-clobber 反例发现，public API 在 `except` handler 内直接抛稳定错误时，虽然使用
`from None`，异常对象的 `__context__` 仍保留 hostile RuntimeError 或 publication error。修复后先退出 handler，
再统一抛 `AShareBacktestArtifactError`，从而同时满足稳定消息、`cause=None` 与 `context=None`，不泄露 TOKEN、
SQL、路径或 PID。正向行为和 P0 rollback 分类未改变。

## 4. 测试边界与覆盖

按任务单 §15，G7F 两个新测试复用已主验模块化 fixture：只在 G7F import 边界 mock public plan verifier/F0
loader，在 G7E import 边界 mock其 public plan verifier。返回值仍是 exact public plan 与 exact、内容绑定且可由
public property 重验的 F0 capability；actual G7E、G7C、F1/F2、G7F 指标/terminal/manifest/receipt 与 P0 均未
mock。该 fixture 不重复证明完整 G1 release 来源，来源闭包由 F0/G7B/G7E 邻接套件承担。

新增测试覆盖：

- G7F plan/F0 各 exact once，actual G7E 恰三次及固定 multiplier/order；
- hostile、nonexact、stale 在任何输出前稳定拒绝且 root 保持空；
- 21 inputs/29 outputs、七表含空表、scenario/root manifest 和 common facts identity；
- scaled cost、gross/2、Decimal return/annualized/fee、benchmark、terminal exit 与 rejection intent 口径；
- metrics/receipt drift、P0 no-clobber、caller result/transition 无入口；
- 三证券五 session golden 与 actual G7E 七表逐表一致，并显式复算三场景指标。

## 5. 验证证据

Windows Miniforge，工作树自身 `src`：

- G7F unit + golden：`10 passed`，耗时 `468.30s`；
- 定向 Ruff：通过；
- mypy `a_share_reporting.py`：通过；
- cold import：通过。

WSL Miniforge `base`，同一工作树：

- G7F unit + golden：`10 passed`，耗时 `379.23s`；
- G7E、P0、G7B、F0、G7C、F1、F2 邻接：`135 passed`，耗时 `478.27s`；
- 定向 Ruff：通过；
- mypy `a_share_reporting.py`：通过；
- cold import：通过。

测试仅出现 Pandera/Polars 已知 deprecation warnings，无失败。WSL 工作树位于 `/mnt/f` DrvFS，以上只作为
双平台兼容证据，不声明 Linux/ext4 Gate。

## 6. 文件范围

- `src/quant/backtest/a_share_reporting.py`：formal builder/verifier、fresh 链、三场景指标、manifest、receipt 与
  whole-tree 验证；
- `src/quant/backtest/__init__.py`：安全导出 formal public API；
- `tests/unit/test_m3_g7f_formal_backtest_artifact.py`：正式合同、反例与事务边界测试；
- `tests/integration/test_m3_g7f_formal_backtest_artifact_golden.py`：五日三场景 golden；
- G7F 任务单状态与本交付报告。

未修改 G7E、P0、G7B、F0/G7C/F1/F2、contracts、schemas、config、receipt/StageRunner 或正式 artifact。

## 7. 剩余风险与下一步

- 模块化 fixture 不等于重新完成 full G1 retained release 来源证明；该边界已由任务单 §15 明确裁决；
- shared worktree 含其他里程碑既有改动，本轮只对 G7F 白名单内差异负责；
- WSL 证据来自 DrvFS，不代表 Linux/ext4 文件系统 Gate；
- 下一步必须由未参与实现的全新外部 Agent 增加 whole-bundle/nested hostile 反例并独立初验，再由主 Agent
  执行最终 fresh、三回放、Decimal、21/29 receipt、双平台与全量回归验收。
