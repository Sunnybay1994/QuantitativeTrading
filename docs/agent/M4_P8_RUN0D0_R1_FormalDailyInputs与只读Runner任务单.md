# M4 P8 RUN-0D0 R1：Formal Daily Inputs 与只读 Runner 任务单

日期：2026-08-14
状态：R1 实现与正常开发检查完成；等待首个 PAPER_CANDIDATE 和真实开盘事实；真实 PAPER 启动仍受 UA-M4-002 控制

## 1. 目标

在不修改既有 `quant.execution.cli` 业务语义的前提下，关闭 UA-M4-004 批准后的三条工程缝隙：

1. 从轻量研究发布目录读取且重新验真的 `PAPER_CANDIDATE` target；
2. 从采集流程独立发布的当日开盘事实包构造 `VerifiedMarketSnapshot`；
3. 组合既有 formal store/gateway/service/broker snapshot 能力，提供只允许 `inspect`、`plan` 的零副作用 daily runner。

本包不创建候选、不联网采集、不批准订单、不提交订单、不注册计划任务、不创建 28 日 soak。策略会话负责首个
`PAPER_CANDIDATE`；数据流程负责开盘事实包。UA-M4-002 批准前，公开 runner 必须拒绝 `approve`、
`paper-submit`、`cancel`、`reconcile`。

## 2. 来源选择

来源只能由 fresh `VerifiedPaperRuntimeEnvironment.config.source_selector` 派生：

- 配置：`configs/trading/sources/{source_selector}.toml`；
- target：`artifacts/research/runs/{target_run_id}`；
- market：`artifacts/paper_inputs/opening/session={YYYY-MM-DD}`。

caller 不得传任意 target/market 文件路径。source 配置必须是 formal classification，绑定 exact target run id、
开盘事实 schema/source version、允许市场和 `close -> next_session_open` 时序。example/development/fixture selector
或配置一律拒绝。

## 3. PAPER_CANDIDATE target

- `run.json` 必须 canonical、`schema_version=lightweight-research-run-v1`、`conclusion=PAPER_CANDIDATE`，且
  `run_id` 由去掉自身后的完整 manifest 重新计算；
- 输出 exact 包含 `target_weights.parquet`，manifest 中 size/SHA 与当前字节一致；整个 run tree exact、无 link/reparse；
- target 必须通过 `TargetWeightSchema`，物理顺序 canonical，单一 `as_of/strategy/version`，并与 run 字段一致；
- 当前包只接受 SH/SZ；将 run 的完整 `candidate_symbols` 域补齐为显式零权重，防止已有持仓因 target 缺行而绕过退出；
- target `as_of` 必须是开市日，且 market calendar 证明 session 是其后第一个共同开市日；
- `receipt_identity` 取 exact canonical `run.json` SHA，`target_identity` 绑定 run id、target bytes和补齐后的交易 target。

## 4. 当日开盘事实包

exact tree 为：`receipt.json`、`instrument.parquet`、`opening_price.parquet`、`price_limit_1d.parquet`、
`suspension_1d.parquet`、`trade_calendar.parquet`。

- publisher 只接受内存 clean frames，不联网；先通过现有 Instrument/PriceLimit/Suspension/TradeCalendar Schema；
- opening price exact 列：`symbol,session_date,open,source,source_snapshot_id,known_at`；`known_at` 为 aware UTC；
- receipt 绑定 session、known-as-of、source version、六文件 exact size/SHA、quality=true、source identity；
- loader 重新读取并验真 exact tree、物理顺序、文件实体与全部经济闭包；只投影 target 与账户持仓所需证券；
- 非 FULL_DAY 必须有 exact opening price；FULL_DAY 用 price-limit `pre_close` 作保守 reference 且始终禁止成交；
- PARTIAL 在本 R1 保守视为 suspended；所有 A股 tick=`0.01`，board lot 从 instrument 获取；
- session 当日 SH/SZ 必须 open；calendar 必须覆盖 target as_of 到 session，证明没有中间共同开市日。

## 5. Planning 与只读 runner

- account 只取 formal broker snapshot port 的 fresh verified account；
- planner config 只由 fresh `VerifiedPaperExecutionPolicy` 的 trading config、cost schedule、minimum notionals和
  A股 rule selector构造；无 caller fee/rule/FX；
- formal daily dependencies 复用已验真的 service composition、gateway factory、store opener、service factory和
  broker snapshot port；
- runner 每次 fresh 重建 source/target/market/account/planner，随后只委派既有 CLI `inspect` 或 `plan`；
- 任一失败稳定为 `PAPER_FORMAL_DAILY_INPUT_INVALID` 或 `PAPER_FORMAL_DAILY_RUNNER_INVALID`，cause/context为空；
- 前置失败零 store mutation、零 gateway dispatch、零新 root、零日志。

## 6. 文件范围

- 新增 `src/quant/execution/paper_formal_daily.py`；
- 必要安全导出修改 `src/quant/execution/__init__.py`；
- 新增 `tests/unit/test_paper_formal_daily.py`；
- 新增 source example 配置；
- 本任务单、交付报告及用户待批示清单。

禁止修改 CLI、planner、service、gateway、store、risk、soak 业务语义；若实际实现必须修改这些模块，停止并重冻。

## 7. 正常开发检查

按外部 Agent 暂停规则，本包由主 Agent 串行实现，不另设“独立初验/自我复审”。运行 focused pytest、定向 Ruff、
mypy 与必要的 CLI 邻接即可；不机械重复全量回归。至少覆盖：RESEARCH_ONLY、错 run hash/输出字节、缺候选零权重、
错 session/PIT、缺 open/limit/instrument、FULL_DAY、source selector/path/link、hostile异常脱敏，以及 mutating action
在任何 service/gateway 前拒绝。
