# M3 G7D-F1 R1 正式 A 股开盘执行事实交付报告

日期：2026-08-09  
角色：实现 Agent  
状态：**实现与自测完成；待未参与实现者独立初验，不声明 G7D-F1、G7D、G7 或 M3 Gate 通过**

## 1. 完成内容

- 在唯一现有 `VerifiedAShareMarketFacts` capability 上新增两个 exact formal 入口：
  `build_formal_a_share_open_execution_states` 与
  `resolve_formal_a_share_order_quantity_rule`。
- 新增稳定异常 `AShareExecutionError("M3_A_SHARE_EXECUTION_INVALID")`；输入、facts property、Polars、
  Schema、日期/证券/生命周期、PARTIAL parser 与算术异常均在离开 active `except` 后统一翻译，
  `cause/context` 为空。
- formal 输入先完成 exact-type/严格字典序检查，再消费 identity；空 `symbols` 只继续读取 benchmark 以验证
  execution date，随后返回精确空 Schema，不读取 instrument/bar/limit/suspension property。
- 非空请求只读取 instrument、benchmark key、bar 的 open/source、suspension 的 scope/detail/source 和 limit 的
  必要字段；不读取 calendar、公司行动、reconciliation、close/high/low/volume/amount、target、label 或账户。
- 对 symbol/date/instrument/lifecycle、冻结板块 prefix/suffix、科创生效日以及 bar XOR FULL_DAY 潜在持仓域做窄重验。
- FULL_DAY、PARTIAL 半开区间、CNY `Decimal("0.01")` 半 tick 含等号和 exact 12 列/dtype/物理顺序均按任务书实现；
  formal 输出仅为可修改的普通 DataFrame，不新增 capability、signer、registry、restore 或 downstream 裸 frame 信任入口。
- 保留全部 development API 和测试；包根仅新增三个安全导出。

## 2. 修改文件

- `src/quant/backtest/a_share_execution.py`：formal 错误、窄验证/投影核心、两个 public API 与安全导出。
- `src/quant/backtest/__init__.py`：新增 formal 安全导出。
- `tests/unit/test_m3_formal_a_share_open_execution.py`：新增 25 个聚焦测试，覆盖任务书正例与对抗边界。
- `docs/agent/M3_G7D_F1_R1正式A股开盘执行事实任务单.md`：状态更新为实现自测完成、待独立初验/主验。
- 本报告。

未修改 Schema、enum、config、F0/G7C API、development 测试、账户/费用/撮合代码、正式数据或 artifact；未联网、
未 add/commit。

## 3. 测试与验证证据

所有命令均在 `artifacts/dev_worktrees/m3-g4-formal` 使用工作树自身 `src`。

### Windows 原生 Miniforge

- F1 + F0：`48 passed in 135.91s`。
- development market-facts + execution：`65 passed in 37.26s`。
- G7C formal + development simulator：`14 passed in 165.19s`。
- 同一进程固定顺序 F0 → G7C → F1 → development facts/execution → G7E：
  `17 passed in 150.79s`。
- Ruff：通过。
- mypy `src/quant/backtest/a_share_execution.py`：通过，无 issue。
- package 冷导入：通过，未加载 `qlib`、`lightgbm`、`mlflow`。

首次把四个定向文件与两个邻接文件串在同一 Windows 承载命令时，承载层在 304.1 秒超时；一次只读进程检查
确认原 pytest 仍存活，等待其退出后才拆分重跑并取得上述明确终态，没有并发启动第二个测试写者。该超时不记为
通过或失败证据。

### WSL Miniforge base

- F1 + F0：`48 passed in 113.72s`。
- development market-facts + execution：`65 passed in 18.58s`。
- G7C formal + development simulator：`14 passed in 132.83s`。
- 同一进程固定顺序探针：`17 passed in 104.48s`。
- Ruff：通过。
- mypy：通过，无 issue。
- package 冷导入：直接参数重跑通过，未加载三个重依赖。

第一次将 WSL 冷导入拼接在静态检查命令后时，引号被 Windows/WSL 承载层错误拆分；该次 Ruff/mypy 已明确通过，
冷导入未执行。随后使用无嵌套 shell 引号的直接参数方式单独重跑并通过。

`git diff --check` 无空白错误；仅有工作树既有 LF/CRLF 提示。

## 4. 可达性边界与风险

- `Suspension1dSchema` 要求 PARTIAL detail 非空。合法 exact capability 测试覆盖 Schema 可签发的未知非空文本和
  全空白文本；空字符串/`None` 仅通过 hostile property 作为防御边界验证，不能伪造成合法 F0 capability，未放宽 F0。
- WSL 工作树位于 `/mnt/f`/DrvFS；上述绿色仅是双平台兼容证据，不是 Linux/ext4 Gate。
- 本包未使用真实数据、真实账户或网络，也未验证后续 F2、完整 G7D/G7E/G7F。
- 实现者自测不能代替全新独立初验和主 Agent 最终验收。

## 5. 建议独立初验重点

1. 增加实现者未使用的 future-field/禁止 property 访问反例，确认空 symbols 与非空请求的最小消费集合。
2. 增加 PARTIAL 09:30 边界或 symbol/date/instrument 域反例，确认不存在排序、去重或自然日修复。
3. 复核 FULL_DAY 带/不带 limit 的投影与双拒语义，以及 formal builder 未产生 `MISSING_OPEN` 成功行。
4. 复跑任务书 Windows/WSL 定向、邻接、Ruff、mypy、冷导入和 fixed-order 探针。
