# A 股港股通个人量化投研交易系统

个人使用的 A 股与港股通量化系统:日频起步,研究与交易解耦,共享同一数据契约与
`target_weight` 接口。先轻量投研,纸面稳定后再逐步接入实盘。

## 文档

| 文档 | 内容 |
|---|---|
| [AGENTS.md](AGENTS.md) | 智能体行为、代码协作、SSOT 与文档同步准则 |
| [karpathy-guidelines.md](karpathy-guidelines.md) | 代码编写与任务执行的基础原则 |
| [A股港股通个人量化投研交易系统调研.md](A股港股通个人量化投研交易系统调研.md) | 技术选型依据与模块设计("为什么") |
| [项目实施路线图.md](项目实施路线图.md) | M0–M5 里程碑与验收标准("何时做、做到什么程度") |
| [正式产物身份、数据溯源与可复现性方法论.md](正式产物身份、数据溯源与可复现性方法论.md) | 产物身份方法、能力边界与研究快线/formal 稳线的取舍 |
| [docs/README.md](docs/README.md) | 顶层文档、Agent 过程证据和归档文档导航 |
| [docs/M3实施与Agent交接.md](docs/M3实施与Agent交接.md) | M3 模块、函数契约、可分派任务包与 G0–G9 验收矩阵 |
| [docs/M3_M4实施总规划.md](docs/M3_M4实施总规划.md) | M3 剩余关键路径、M4 纸面交易闭环与 Grok 分包顺序 |

## 目录结构

```text
quant/
├─ pyproject.toml            # 依赖:核心 / data(Tushare及校验源) / research / dev
├─ configs/
│  ├─ research/              # 股票池、因子、模型、成本(带版本与有效期)
│  └─ trading/               # 非秘密交易参数;实盘默认关闭
├─ src/quant/
│  ├─ domain/                # 数据契约(Pandera)与枚举 —— 全系统唯一真源
│  ├─ data/                  # 原始采集接口、raw/clean 分层、质量门禁
│  │  └─ connectors/         # 第三方数据源薄适配器（SDK 仅在这里导入）
│  ├─ factors/               # 因子定义与注册(M2/M3)
│  ├─ strategies/            # Strategy 接口:as_of 可知数据 → target_weight
│  ├─ research/              # 研究编排 CLI；不承载数据源或交易逻辑
│  ├─ portfolio/             # 组合约束与目标订单(M4)
│  ├─ backtest/              # 统一市场约束回测(M2/M4)
│  ├─ execution/             # 纸面账户、OMS、风控、券商 Gateway(M4/M5)
│  └─ reporting/             # 日报、归因、告警
├─ tests/                    # unit / integration / fixtures(黄金数据集)
├─ data/                     # raw / clean / features / qlib / legacy(不进 Git)
├─ artifacts/                # 回测、模型、报告及历史实验产物(不进 Git)
├─ docs/                     # 顶层入口；agent/ 过程证据；archive/ 历史文档
└─ archive/                  # 绿地重建前旧代码/Notebook；生产代码不得引用
```

## 架构铁律

1. 券商 API 只允许出现在 `execution` 的 Gateway 适配器内部。
2. 数据源 SDK 只允许出现在 `data/connectors` 内部;换源不改下游。
   只有 `quant.data` 的显式 repository/工具可读取项目 `data/`；其他层不得直接读取数据目录。
3. 策略只输出 `target_weight`,不做 IO、不碰订单。
4. 原始数据(raw 层)不可覆盖;clean 层必须通过 Pandera 质量门禁。
5. 财务数据用真实披露时间(PIT);信号可知时间与成交时间分离。
6. 实盘前:程序化交易报备(第零道门)+ 回测/样本外/仿真/影子/小资金五道门。

## 快速开始

```bash
# Gate / 平台特有终验：WSL Miniforge base（Python >= 3.10）
conda activate base
pip install -e ".[dev]"          # 核心 + 测试
pip install -e ".[data]"         # M1:Tushare + 免费校验源
pip install -e ".[research]"     # M3:MLflow/LightGBM/QuantStats
# 主体仍使用 base；版本不兼容工具仅按 AGENTS.md §8 的独立环境规则执行。
# Qlib 0.9.7 已在 py312 验收；不要在 base 安装，相关命令使用：
# /home/mabw/miniforge3/bin/conda run -n py312 <command>

python -m pytest -q              # 运行契约单测

# Windows 普通开发反馈环（不替代 WSL Gate）：
# D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_journal_lock.py -q
```

### M3 G1 工作流 CLI（R1C）

唯一入口：`python -m quant.research.m3.run_g1`。公共参数只有 `--config`（必填）与可选
`--project-root`（默认当前工作目录，测试用）；`run-all` 另支持
`--stop-after {INDEX,HISTORY,REFERENCE,PREPARE,PUBLISH}`（默认 `PREPARE`）；`history` 另支持可选
`--max-new-requests N`（严格正整数，按本轮新提交 request identity 计数有界恢复；省略则全量推进）。
禁止 `--token` / `--raw-root` 等覆盖。业务值来自 C0；Tushare token 仅由本地忽略配置加载。

```bash
/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  status

/home/mabw/miniforge3/bin/conda run -n base \
  python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  run-all --stop-after PREPARE
```

子命令：`status` | `index` | `history` | `reference` | `prepare` | `publish` | `run-all`。
单段命令不自动补前置；只有 `run-all` 按序推进。stdout 一行 JSON；失败时 stderr 为
`operation:error_code`。

### Tushare Pro 私密配置

实际 Token 只填写到 `configs/tushare.local.toml`。该文件被 `.gitignore` 的通配规则和显式规则双重排除；不要把 Token 写入 example、环境日志、命令行或聊天内容。

```toml
[tushare]
token = "在本地文件中填写"
```

安装 data 依赖后可执行脱敏检查，输出中的 Token 永远固定为 `<redacted>`：

```bash
python -m quant.data.check_tushare --date 2026-07-10
```

如需把私密文件放在别处，只设置 `QUANT_TUSHARE_CONFIG` 为配置路径；不支持通过命令行直接传 Token。

## 日线数据更新（M1）

当前以 Tushare Pro 为研究数据主源，AKShare/BaoStock 用于交叉校验和降级。证券列表必须显式传入，尚未定义正式股票池前不提供隐式全市场默认值。
沪深日线更新默认要求对应 clean 交易日历已存在且目标日期开市；应先执行下方 `update_calendar`。`--skip-calendar-check` 仅用于诊断，不属于正常更新流程。

```bash
python -m quant.data.update \
  --source tushare \
  --date 2026-07-10 \
  --symbols 000001.SZ
```

需要由外部调度器重复触发的日常任务应使用带单实例锁和不可变完成收据的上层入口；同一严格运行规范已完成时会先验真 raw、质量报告和 clean 逻辑切片，再返回 `ALREADY_COMPLETE`，不会构造 pipeline 或再次调用数据源：

```bash
python -m quant.data.run_daily \
  --source tushare \
  --date 2026-07-10 \
  --symbols 000001.SZ
```

运行状态保存在 `data/run_state/m1_daily/<run_id>/`。命令仍要求显式日期和证券集合，不负责创建或管理 cron/Windows Task Scheduler；路线图中的“连续 5 个真实交易日无人干预”必须另以预配置系统调度历史和五份验真收据证明。底层 `quant.data.update` 保留用于人工诊断和已有脚本，不提供完成收据或跨进程单写者保证。

Tushare A 股成交量单位为手、成交额为千元，mapper 会分别转换为股和元。港股原始单位已经是股和港元，不做倍数转换。当前账号可访问 `hk_daily`，但频率只有 1 次/小时且无 `hk_adjfactor` 权限；需要仅验证不复权港股行情时必须显式加 `--without-adjustment-factors`，该结果不能用于复权收益研究。

单日更新按 A 股/港股端点各执行一次全市场请求，再在本地筛选证券；不会按证券逐只消耗港股的小时额度。若行情 raw 已成功留档、但后续因子权限或 mapper 失败，可显式重处理不复权快照：

```bash
python -m quant.data.reprocess_bar \
  --raw-path data/raw/tushare/bar_1d/date=YYYY-MM-DD/<snapshot>.parquet \
  --source tushare --symbols 00700.HK --date 2026-07-10
```

A 股可使用 BaoStock 独立抓取同一批次，并生成跨源报告：

```bash
python -m quant.data.update \
  --source baostock \
  --date 2026-07-10 \
  --symbols 000001.SZ

python -m quant.data.compare \
  --start 2026-07-10 \
  --end 2026-07-10 \
  --symbols 000001.SZ
```

沪深港交易所基础日历和股票主表默认通过 Tushare 更新；A 股 ETF 仍由 BaoStock/ETF 专用接口补齐：

```bash
python -m quant.data.update_calendar \
  --source tushare \
  --market SH \
  --start 2026-01-01 \
  --end 2026-12-31

python -m quant.data.update_calendar --source tushare --market HK \
  --start 2026-01-01 --end 2026-12-31
python -m quant.data.update_instruments --source tushare --market SH
python -m quant.data.update_instruments --source tushare --market SZ
python -m quant.data.update_instruments --source tushare --market HK
python -m quant.data.audit_instruments
```

Tushare 港股的开盘竞价价可能落在供应商所报日内 high/low 之外。raw 始终保留供应商原值；mapper 仅在
原 high/low 自洽且 close 位于原区间时扩展 canonical high/low 以包含 open。A 股开盘越界、港股收盘
越界、`high < low` 或非正价格仍由 `Bar1dSchema` 拒绝。

`hk_daily` 当前实测可用逗号分隔两代码返回完整 60 日区间，但港股接口官方文档没有明确承诺这一语法。
批量历史回填只能通过逐批精确覆盖、5000 行截断、重复键和目标集合 Gate 的可恢复 manifest 使用；任何
行为漂移均 fail closed，不在同一运行中静默追加单代码或逐日请求。

当前冻结计划位于 `artifacts/data_quality/hk_history/hk60_2026-07-10/plan.json`。每次执行最多发出一个新
请求，并从 P1 seed 或最近 attempt 起强制冷却至少 3,600 秒；同一 plan 只能由 WSL writer 执行：

```bash
python -m quant.data.backfill_hk_history \
  --plan artifacts/data_quality/hk_history/hk60_2026-07-10/plan.json \
  --data-root data \
  --journal-root artifacts/hk_history_backfill/ffbf8f345626b9db834a7b4c31fa8c31a6b60ffe5053ab4953a27bb2c4c50a03 \
  --config configs/tushare.local.toml
```

API 异常留下的 attempt 在冷却后仍需显式 `--confirm-uncertain-retry`；完整 request raw/receipt 会直接复验，
不会再次联网。8 批全部 PASS 前禁止 `--finalize`；finalize 只发布 Tushare 已闭合的 612 只股票，
`02983.HK` 仍保持显式未解决，不能据此宣称全量 HK60 Gate 通过。

Tushare `hk_basic` 只覆盖港股股票。HKEX 公共网站现行条款禁止未经书面许可的程序化/脚本化访问、
系统性抓取和建库，因此 `hkex-etp` 公共网页连接器已 fail closed：

```bash
python -m quant.data.update_instruments --source hkex-etp --market HK \
  --as-of 2026-07-10 --symbols 02800.HK 03033.HK
```

该命令固定返回 `HKEX_ETP_LICENSE_REQUIRED`，且不会发起网络请求或写 raw/clean。只有取得 HKEX 书面许可
或订阅其正式 Historical Data/API 产品并留存授权证据后，才可接入新的 licensed adapter；不得恢复网页
token/JSONP 抓取。现有离线 mapper 仅用于验证已获许可或用户合法提供的原始文件，不代表数据获取授权。

HKEX 公告确认的临时股票柜台使用版本化生命周期配置投影，不能混入 Tushare 股票或 ETP mapper：

```bash
python -m quant.data.update_instruments --source hkex-notice --market HK \
  --as-of 2026-07-10 --symbols 02983.HK \
  --notice-config configs/instruments/hk_temporary_counters_2026.toml
```

配置以 `(symbol, list_date)` 标识可复用的临时代码生命周期，并分别保存最后交易日、证书截止日和 CCASS
转换截止日；只有最后交易日可映射为 `delist_date`。公告事实先写不可变 raw，再发布 as-of Instrument 投影。

港股基础日历不能只依赖 Tushare 的开/休市标记。更新时还会加载
`configs/calendars/hk_market_YYYY.toml` 中版本化的 HKEX 证券市场年度通告：
先核对官方全日休市，冲突时拒绝发布 clean；再补充数据接口未提供的半日市。
2026 年通告 `CT/075/25` 对应 14 个工作日全日休市和 2 月 16 日、12 月 24 日、
12 月 31 日三个半日市。跨自然年更新必须拆分执行，未配置年度通告时显式失败。

当前 2000 积分不能调用 Tushare `etf_basic`（需 8000）或 `fund_daily`（需 5000），因此 A 股 ETF
主表与行情不假装走 Tushare；港股 ETF 也不得改用未获许可的 HKEX 公共网页端点，完整 HK Instrument
主表仍等待合规来源。现有 BaoStock clean 主表覆盖 903 只沪市 ETF、695 只深市 ETF，核心
`510300.SH`、`159919.SZ` 已通过覆盖审计。

多日回补由 clean 日历生成预期开市日，并对每个证券执行完整性门禁：

```bash
python -m quant.data.backfill \
  --source tushare \
  --start 2026-07-06 \
  --end 2026-07-10 \
  --symbols 000001.SZ
```

输出约定：

- `data/raw/{source}/bar_1d/date=YYYY-MM-DD/`：不可变原始 Parquet 与 JSON 血缘元数据。
- `data/clean/bar_1d/date=YYYY-MM-DD/data.parquet`：通过 Schema 和质量门禁的幂等日分区。
- `data/clean/trade_calendar/market={SH|SZ|HK}/data.parquet`：三地交易所基础日历。
- `data/clean/instrument/market={SH|SZ|HK}/data.parquet`：股票/ETF 证券主表。
- `data/clean/adjust_factor/source={tushare|baostock}/data.parquet`：累计后复权因子变化事件。
- `data/clean/research_price_1d/date=.../data.parquet`：研究专用调整收盘价；不得用于账户核算或成交价。
- `artifacts/data_quality/bar_1d/`：每次 raw 快照对应的空值、缺失观测、重复键、OHLC 和异常收益跳点报告。
- `artifacts/data_quality/cross_source/`：AKShare/BaoStock 收盘价覆盖差异与相对价差报告。

AKShare 沪深日线按东方财富股票、新浪股票、东方财富 ETF 顺序尝试，并在 raw 数据的 `_endpoint` 字段保留实际端点。任一网页端点都可能临时不可用；此时使用 `--source baostock` 换源，不能绕过质量门禁或静默填充数据。

`bar_1d` 始终保存不复权 OHLC；`adj_factor` 的 canonical 口径是累计后复权因子，研究价格按 `raw_price × adj_factor` 计算。Tushare/BaoStock 更新会把行情与因子分别写入 raw，再按生效日期 as-of 匹配；长区间 Tushare 请求会切片以避开行数上限，并把逐日因子压缩为变化事件。账户核算不得使用复权价。

只要更新命令启用了复权，复权因子必须覆盖请求中的每一只证券，否则 raw 保留但
拒绝发布 clean。数据源返回空因子不能静默解释为 `adj_factor = 1`；确实只需要
不复权行情时必须显式使用 `--without-adjustment-factors`。

## 港股通官方基础数据（M1）

港股通名单按路由保存“当前快照”和“调整事件”两类事实，禁止把当前名单用于历史回测。上交所接口覆盖沪港通名单及调整事件；深交所接口覆盖深港通名单、调整事件和逐日交易日历：

```bash
python -m quant.data.update_connect --route SH_CONNECT --table snapshot
python -m quant.data.update_connect --route SH_CONNECT --table events
python -m quant.data.update_connect --route SZ_CONNECT --table snapshot
python -m quant.data.update_connect --route SZ_CONNECT --table events
python -m quant.data.update_connect --route SZ_CONNECT --table calendar \
  --start 2026-01-01 --end 2026-12-31
python -m quant.data.update_connect --route SH_CONNECT --table calendar \
  --start 2026-01-01 --end 2026-12-31

python -m quant.data.rebuild_connect_universe \
  --route SH_CONNECT --baseline-date 2026-07-10
python -m quant.data.rebuild_connect_universe \
  --route SZ_CONNECT --baseline-date 2026-07-10

# reverse-audit 模式（消费 E3/E4 verified audit；默认仍为 snapshot 兼容旧命令）
python -m quant.data.rebuild_connect_universe \
  --route SZ_CONNECT --mode reverse-audit \
  --baseline-date 2016-12-05 --snapshot-date 2026-07-10 \
  --expected-baseline-count 417 --dry-run
python -m quant.data.rebuild_connect_universe \
  --route SZ_CONNECT --mode reverse-audit \
  --baseline-date 2016-12-05 --snapshot-date 2026-07-10 \
  --expected-baseline-count 417

python -m quant.data.audit_calendars --year 2026
```

默认 `--table events` 仍走幂等 upsert（唯一键含 `action`）。若需纠正由错误
mapper 生成的既有 clean 事件，须**显式**使用受控原子替换，且仅允许与 events 同用：

```bash
python -m quant.data.update_connect --route SH_CONNECT --table events --replace-clean
```

警告：`--replace-clean` 会整文件替换该 route 的 clean 事件，不 concat 旧行；不会自动
重建 universe，也不会改动其他 route / snapshot / calendar。未经授权不要对项目真实
`data/` 执行；raw 在 mapper/clean 失败时可保留，但失败时原 clean 不变。

只读逆向审计（不发布 snapshot/universe、不写 artifact、不联网）可用：

```bash
python -m quant.data.audit_connect_eligibility \
  --route SH_CONNECT --snapshot-date 2026-07-10 \
  --baseline-date 2014-11-17 --expected-baseline-count 268
```

成功时 stdout 仅一行严格 JSON（含 counts/status=PASS，不含 symbols/path）；失败非零且不
输出 baseline_symbols 全集。默认 `--data-root data`。

可选 `--preview-membership`：仅在 audit PASS 后只读预览成员区间统计（追加
`membership_rows` / `membership_symbols` / `coverage_start` / `open_intervals`），仍不写
`clean/universe_membership`、不输出 symbol 全集或路径。未指定该 flag 时原有 JSON 字段不变。

可用一条 DuckDB 查询把 `as_of` 时点有效的港股通成员与该时点之前的最近 N 个
源内行情观测拼接起来。默认 report 模式 stdout 输出单行 JSON，显式报告 coverage
（eligible / returned / missing / short / min / max / `is_full_window` 等），允许新上市或
短历史证券，但不再静默忽略不完整窗口：

```bash
python -m quant.data.query_universe \
  --universe SH_CONNECT --as-of 2026-07-10 \
  --source tushare --observations 60 \
  --output artifacts/queries/sh_connect_2026-07-10_tushare.parquet
```

正式完整窗口证据须加 `--require-full-window`：任一 eligible 缺失或观测数不足 N 时，
以稳定错误码 `BAR_WINDOW_INCOMPLETE` 非零退出，且即使指定了 `--output` 也不写文件。
该命令只提供查询与审计能力，不表示真实港股通 60 日全市场覆盖已经取得。

新上市股票天然不足 N 个交易日时，可显式改用正交 Gate `--require-available-history`。它读取 clean HK
`trade_calendar`、`instrument`、双 Route `connect_snapshot/connect_event`：优先用通过领域 Schema 的官方
资格 `security_type` 排除 ETF；官方 STOCK 仍必须有 Instrument，并用其 `list_date/delist_date` 计算最后
N 个精确开市日；官方为 OTHER/缺失时才回退 Instrument 分类。同一证券出现 STOCK/ETF 冲突、引用缺失
或不可信时稳定失败 `BAR_WINDOW_REFERENCE_INVALID`，精确日期有缺口或混入非开市/上市前日期时失败
`BAR_WINDOW_AVAILABLE_HISTORY_INCOMPLETE`，两种失败都不会写 `--output`。当前没有逐日停牌历史 SSOT，
所以 Instrument 的当前 `SUSPENDED` 状态不会自动豁免缺失日。该参数不改变 `--require-full-window` 的原语义；
两者同时指定时必须同时通过。

成员区间用于确定 `as_of` 时点的证券集合；为了计算滚动特征，返回的历史行情
可以早于成员的 `effective_from`。回测中每个交易日是否仍具备买入资格必须由
回测层按当日成员状态另行检查，不能把本查询结果直接当成持续可交易证明。

对应 clean 资产：

- `connect_snapshot/route=.../date=...`：不可覆盖的时点名单；
- `connect_event/route=...`：按官方生效日幂等合并的 `ADD/REMOVE` 事件；
- `connect_calendar/route=...`：双路由逐日开通、半日市和节假日名称；
- `universe_membership/universe=...`：仅从明确基线日向后可证明的成员区间。

`rebuild_connect_universe` 默认 `--mode snapshot` 保持旧语义（以 `--baseline-date` 快照为起点正向重建）。
`--mode reverse-audit` 须同时提供 `--snapshot-date` 与 `--expected-baseline-count`，并依次调用
`verify_reverse_eligibility_history` → `build_membership_intervals_from_reverse_audit` →
受控 `replace_universe`；`--dry-run` 两模式均可，只构建/验证不写 universe。成功 stdout 单行 JSON
含 `route/mode/baseline_date/snapshot_date/rows/symbols/coverage_start/open_intervals/published/status`，
不含 symbol 全集或物理路径。snapshot 模式禁止 reverse 专用参数。未经授权不要对项目真实 `data/` 执行发布。

沪港通没有与深交所同等稳定的逐日机器接口，因此使用版本化、人工复核的上交所年度公告配置叠加沪市基础日历生成；配置保留公告 URL、文号、发布日期、全日及半日例外。深港通仍直接使用深交所机器接口，两条路由互不冒充。日历审计会检查双路由差异，以及港股通开通但内地或香港基础市场休市的非法状态。

## 当前状态

M0 已通过验收；M1 已完成 A 股/ETF 数据、三地基础日历与股票主表、双路由港股通快照/事件/日历、基线后成员区间及“时点股票池 × 历史行情窗口”查询，HK licensed provenance 与五日自然窗口仍开放。M2 的数据契约、策略接口、统一日频回测、walk-forward、成本压力、轻量不可覆盖 `run.json` 和目标缺口诊断已经达到**投研框架 MVP 完成**；当前唯一前台关键路径是策略假设—证伪与前向观察，PAPER MVP 为第二优先级，M3/M4 formal 工程以单一在制包在后台推进，不再反向阻塞研究。研究、PAPER 和 formal 复用同一 Schema、市场规则、费用和账户计算；候选晋级时通过正式入口受控重跑，不能把轻量产物原地冒充正式产物。月度 S2 两个样本外测试折均为正；双月调仓和一位排名保留缓冲均未满足各自预注册条件，已记为 `REJECTED`；固定 60 观测、12% 年化、无杠杆的波动率目标与最小两只 ETF 分散化均通过各自预注册条件，但因没有真正前向样本、且分散化第一折的验证选择来自零交易并列，均保持 `RESEARCH_ONLY`。M3 已具备 Windows G1 正式发布物、G2–G7 formal artifact/fresh verifier、G8 StageRunner/tracking/reproducibility 与 fake full DAG；G9A/G9B 和资源受限性能闭包已完成。首轮 honest 300 业务 CLI 已完成，但集成验收在 stage root 新增文件集合处失败，completed resume 尚未执行；下一步用小型探针定位，不重复长链，也不阻塞 S2+。M4 formal runtime/policy/binding/account/store 与只读 broker snapshot port 已完成 Windows 工程闭环；第一波 A 股/ETF PAPER 只要求人工确认、订单幂等、资金/可卖量、持久账本和日终对账，完整来源证明留给 formal/影子/实盘候选，gateway dispatch 仍等待 `UA-M4-003`，service/runner/28 日 soak 尚未开始。`py312` 已验收 Qlib 0.9.7 兼容性且 base 未变；Linux/ext4 当前按用户指示暂不实施。详见[路线图](项目实施路线图.md)、[方法论](正式产物身份、数据溯源与可复现性方法论.md)和[持续审批事项](docs/agent/用户待批示与参与事项.md)。研究阶段可使用本地 ignored Tushare token，启用实盘前必须轮换。

## M2 基线策略（工程闭环完成，策略有效性继续观察）

版本化配置位于 `configs/research/m2_baseline.toml`。`ETF_POOL_M2_V1` 冻结了宽基、
行业和港股主题三组共 11 只 ETF，本地证券主表已核验全部为上市 ETF。当前实现：

- 因子层由标准研究价格计算 20/60/120 日动量和 60 日对数价格回归斜率×R²；
- 等权与 ETF 趋势策略只输出 `TargetWeightSchema`，不执行数据下载或下单；
- 绝对趋势不通过时保留现金；证券在信号日缺数时不沿用陈旧信号；
- 回测时间对齐只允许 `as_of` 之后的下一市场开市日，不允许同收盘价成交。

BaoStock 已取得 11 只 ETF、2026-01-05 至 2026-07-10 共 1,364 行不复权 raw；
其 ETF 专用复权因子为空，因此不能进入常规 `bar_1d × adj_factor` 收益路径。
M2 改用既有不复权 raw 与 AKShare/Sina 除息日累计分红事件构造分红再投资总回报
指数，并单独写入 `research_price_1d`。东方财富 HFQ 只作诊断，不与总回报方法混用。

```bash
python -m quant.data.reprocess_etf_total_return \
  --raw-path data/raw/baostock/bar_1d/date=YYYY-MM-DD/<snapshot>.parquet \
  --start 2026-01-01 --end 2026-07-10 \
  --symbols 510300.SH 159919.SZ

python -m quant.research.run_etf_trend --as-of 2026-07-10
```

真实烟雾结果：11 只候选统一采用 `TOTAL_RETURN_DIVIDEND`，输出 44 个因子值；
2026-07-10 信号选择 `159922.SZ`、`510500.SH`，各 45%，保留 10% 现金，
安排到 2026-07-13 执行。该结果只证明链路和时间语义贯通，不构成策略有效性结论；
后续已补足长期历史并按下述 walk-forward 协议重新评估。

长期历史现已通过 AKShare/Sina ETF 日线端点回补：2023–2025 共 7,997 行，
11 只候选各 727 个交易观测，并与 2026 BaoStock 增量衔接。东财端点失败时新浪
端点作为显式 fallback，raw 的 `_endpoint` 保留实际来源；东财 A股/ETF 成交量由
“手”转换为“股”，新浪端点本身已是股，不重复放大。

```bash
python -m quant.data.backfill \
  --source akshare --start 2023-01-01 --end 2025-12-31 \
  --symbols 510300.SH 159919.SZ ... --without-adjustment-factors

python -m quant.research.run_s1_walk_forward
```

S1 使用 24 个月训练/因子预热、6 个月验证选参、6 个月冻结测试、每 6 个月滚动：

- 第一折测试（2025 下半年）：1×成本后 `+19.98%`，Sharpe `2.10`，最大回撤 `-7.53%`；
- 第二折测试（2026 上半年）：1×成本后 `-3.26%`，Sharpe `-0.32`，最大回撤 `-12.61%`；
- 两折顺序复合收益 `+16.06%`，但只有 1/2 折为正；
- 0.5×/1×/2× 成本压力均已输出，第二折在所有成本场景下仍为负。

因此当前结果只能说明策略在不同阶段表现不稳定，不能据第一折高收益宣称 alpha。
此外 `ETF_POOL_M2_V1` 到 2026-07-12 才正式冻结，历史回看仍存在候选池后见偏差；
只有此后新增的真正前向样本能消除该问题。完整产物在
`artifacts/research/m2/s1_walk_forward/`，其中 `quantstats/` 保存各测试折的
1×成本 HTML tear sheet。

策略研究快线随后加入 `configs/research/m2_s2_regime.toml`：只有当 `510300.SH`
的 20/60/120 日动量及同一验证候选的回归趋势均为正时，才允许原 ETF 趋势组合持仓，
否则显式回到现金。数据、候选池、时间切分、下一开市日成交和费用均保持不变。当前版本结果：

- S1 两折 `+19.98% / -3.26%`，顺序复合 `+16.06%`，1/2 折为正；
- 同折 S0 等权为 `+14.36% / -5.07%`，顺序复合 `+8.57%`，1/2 折为正；
- S2 两折 `+7.99% / +6.40%`，顺序复合 `+14.90%`，2/2 折为正；
- S2 两折在 2×成本下仍分别为 `+7.51% / +5.93%`；
- S2 两折单边换手约为初始资金的 `1.92× / 1.86×`，高于 S0 的 `0.60× / 0.59×`；
- S2 降低了第一折收益但修复了第二折负收益，尚未在收益、回撤和换手上全面占优，当前仅支持继续研究，不支持晋级 PAPER。

轻量产物位于 `artifacts/research/runs/<run_id>/`，包含 `run.json`、报告、目标权重、
目标持仓缺口、NAV 和成交；相同输入重跑复用相同 `run_id`，不允许覆盖已有不同字节。
兼容 ETF 回放的 `test_target_gaps.parquet` 只陈述可由该入口直接证明的整手、现金和缺
开盘价缺口；停牌、涨跌停和 T+1 拒单仍以统一日频模拟器或 formal 执行模拟为准。运行示例：

```bash
python -m quant.research.run_s1_walk_forward --config configs/research/m2_s2_regime.toml
```

针对 S2 高换手，项目随后只改变一个变量，将调仓频率从每月改为每两月。该假设没有通过：
第一折 `+7.99%` 基本不变，但第二折从 `+6.40%` 降为 `-3.36%`，两折复合仅
`+4.36%`，只剩 1/2 折为正；尽管第二折单边换手降至约 `1.30×`，仍不足以补偿稳定性
损失。该失败运行以 `REJECTED` 保存在 run ID
`1383e5b3074907122717c4e3ccd8b917f54e9641c38bf43a9b1594bea32574f2`，月度 S2 继续作为
当前研究基线。

第二个换手假设保持月度信号不变，只允许上期目标在当前排名落到 `Top-K+1` 时继续保留，状态由
组合层显式传入，策略仍不读取账户。结果具有探索价值但未通过预注册条件：第一折验证选择
`Top-K=1`，缓冲没有生效，收益/换手仍为 `+7.99% / 1.92×`；第二折换手从约 `1.86×`
降到 `1.76×`，收益提高到 `+12.82%`。因为“两个测试折都降低换手”没有成立，该运行仍按
`REJECTED` 保存，最终 run ID 为
`24db2ef96866097b9d0312776d865d1284a421508378f8ba2d4d39ac7284a5df`。不得事后放宽条件把它
改称通过。

第三个单变量实验保持月度调仓、状态过滤、Top-K、候选池和成本不变，仅对信号日可见的最近
60 个共同收益观测估计目标组合波动率；当年化波动率超过 12% 时只降低总敞口，不加杠杆、
不改变证券选择。它满足了预注册条件：两折最大回撤由月度 S2 的约 `-12.99% / -5.08%`
改善为 `-4.93% / -4.01%`，两折成本后收益仍为正，分别约 `+3.73% / +4.64%`，2×成本
下也仍为正。代价是两折复合收益从约 `+14.90%` 降为 `+8.55%`，实际年化波动率约为
`11.19% / 10.35%`。该结果只能支持继续研究，不能替代真正前向观察，仍以 `RESEARCH_ONLY`
保存在 run ID `b61ae28d7efc370ca5433c8138d0968cb7d56d1ded20079d718a765e51131039`；同一代码版本的
月度 S2 基线 run ID 为 `f5674056ea7b2944be2ce03db5d0e44b40506b68e316acf961945f899b24cb00`。

第四个单变量实验只把 walk-forward 的 Top-K 候选从 `[1,2,3]` 收窄为 `[2,3]`，禁止单只
ETF 集中持仓。第一折因此选中 Top-K=2，收益由约 `+7.99%` 提高到 `+13.94%`，最大回撤由
`-12.99%` 改善为 `-8.98%`；第二折原本就是 Top-K=2，收益和回撤保持约 `+6.40% / -5.08%`。
两折复合约 `+21.23%`，且 2×成本下仍均为正，满足预注册的正收益与回撤条件。但第一折验证期
获胜参数仍来自零交易并列，尚不能证明稳定的参数选择能力，因此结果继续标记为 `RESEARCH_ONLY`，
run ID 为 `4ea4493f798ed5df8ac61d316f74e56fbfd87730bc6ff578bf979705acb5f1e6`，不晋级 PAPER。

第五个实验不再调整 Top-K，而用全候选市场参与宽度作为独立风险信号：Top-K 固定为2、回归窗口固定为60，
只有 11 只冻结 ETF 中严格多数的 120 日总回报动量为正才允许持仓，阈值不参加搜索。结果两折 1×收益约
`+26.49% / +3.63%`，2×成本后仍为正，复合约 `+31.09%`；但相对最小两只基线，最差回撤几乎没有改善，
且第一折单边换手由约 `2.52×` 增至 `3.25×`，未通过预注册的回撤和换手条件。因此最终以 `REJECTED`
和 run ID `25ed53dfff8afbd35ec2141bd6fff0764a090b30ce1651f9b8a62dd3dd65d717` 留档。

第六个实验把证券排名替换为固定 60 日已实现波动率，宽基准趋势过滤、Top-K=2、月度执行和成本均不变，
且不搜索窗口。两折 1×收益约 `+10.58% / +2.89%`，最差回撤改善到约 `-5.55%`，单边换手降到
约 `0.95× / 1.35×`；但两折复合收益只有 `+13.78%`，仅保留最小两只比较器约 64.92%，没有达到
预注册的 80%。因此以 `REJECTED` 和 run ID
`279e5411ca0aec53c8eb66aa1b1e8cd67a4815c7f2be6fd066fb48861e7f1840` 留档，不继续在相同两折上搜索波动率窗口。

为避免继续在同一历史两折上调参，项目提供了只用于该冻结候选的前向观察入口。配置
`configs/research/m2_s2_minimum_breadth_forward.toml` 绑定上述 run ID、来源配置 SHA、候选冻结日和
固定参数；入口只接受 `2026-08-31` 起的完整自然月最后一个 SH 开市日，并要求全部候选总回报价格覆盖
信号日和最小历史。输出位于 `artifacts/research/forward_observations/<observation_id>/`，包含目标权重、
下一交易日计划和不可覆盖的 `observation.json`。它始终是 `RESEARCH_ONLY` 且明确
`deployment_authority=false`，不能送入 PAPER 或实盘：

```bash
python -m quant.research.run_s2_forward_observation --as-of YYYY-MM-DD
```

当前数据只到 `2026-07-10`，因此尚不存在合格的真实前向观察；不得用部分月份或回填旧日期冒充。

S0 使用同一候选池运行买入持有和等权月调仓。成交与估值使用不复权
`bar_1d`，总回报价格只用于反推出除息日现金分红；模拟器支持次日开盘、整手、
最低佣金、比例佣金和滑点：

```bash
python -m quant.data.reprocess_bar \
  --raw-path data/raw/baostock/bar_1d/date=YYYY-MM-DD/<snapshot>.parquet \
  --source baostock --start 2026-01-01 --end 2026-07-10 \
  --symbols 510300.SH 159919.SZ

python -m quant.research.run_s0
python -m quant.research.reconcile_s0

python -m quant.reporting.quantstats_report \
  --nav-path artifacts/research/m2/s0/nav.parquet \
  --output-dir artifacts/research/m2/s0/quantstats
```

2023-01-01 至 2026-07-10 的长期结果：100 万初始资金下，买入持有收益
`+2.556%`（零成本 `+2.666%`，成本拖累 `-0.110%`）、最大回撤 `-32.136%`、
费用 `249.92` 元；等权月调仓收益 `+3.684%`（零成本 `+4.156%`，成本拖累
`-0.472%`）、最大回撤 `-32.651%`、费用 `2,436.62` 元。产物位于
`artifacts/research/m2/s0/`，其中 `quantstats/` 保存两份 HTML tear sheet。
QuantStats 是 `research` 可选依赖，不进入交易运行时依赖。统一日频事件模拟器已覆盖 ETF/股票涨跌停拒单、
股票 T+1、停牌估值和版本化费用压力；成本参数仍是研究假设，真实券商账单校准属于后续 M4 运维边界。详见
[`M2 U1 最终验收报告`](docs/agent/M2_U1统一股票ETF日频事件模拟器主Agent最终验收报告.md)。
S0 的数据与收益口径由下述独立指数检查验收。

独立指数校验使用中证指数官方 2026-03-31 事实表的沪深300 YTD `-3.89%`。
BaoStock 同期收盘计算为 `-3.8854%`，绝对误差 `0.0046%`，通过配置中的
`0.01%` 容差。2026-01-06 至 2026-07-10，`510300.SH` 总回报与沪深300
日收益相关系数 `0.9948`、年化跟踪误差 `1.90%`；成本后账户收益 `1.975%`，
指数价格收益 `1.305%`，净差 `0.670%`。价格除息、现金分红和成本已分层，分解
残差为 0。报告位于 `artifacts/research/m2/s0_reconciliation/`。

---

本项目不构成投资建议。实盘规则、费用和权限以交易所及开户券商最新文件为准。
