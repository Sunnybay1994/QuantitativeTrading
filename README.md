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

历史 R1 冻结计划位于 `artifacts/data_quality/hk_history/hk60_2026-07-10/plan.json`。该计划已因
`01065.HK@2026-05-05` 缺少权威无交易证据而 fail closed，现只作为审计输入保留，不得继续执行或补写。
取得许可允许的 HKEX Daily Quotations（或同等级官方历史产品）raw 后，必须生成独立 v2 plan 与全新 journal；
每次网络执行仍最多发出一个新请求，并从 seed 或最近 attempt 起强制冷却至少 3,600 秒。历史命令形态为：

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

v2 plan 可用 `--recover-existing-only` 在全新 journal 中离线复验并恢复既有 COMPLETE raw；该模式在
connector 构造前分流，严格零网络、零 intent/attempt/failure/clean/finalize 写入，遇首个 ABSENT raw 返回
`HK_HISTORY_INCOMPLETE`。权威 evidence 尚未形成前不得创建或运行正式 v2 plan。

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

M0 已通过验收；M1 已完成 A 股/ETF 数据、三地基础日历与股票主表、双路由港股通快照/事件/日历、基线后成员区间及“时点股票池 × 历史行情窗口”查询。M2 已完成趋势因子、策略接口、长期总回报研究价格、S0/S1 walk-forward、成本压力、独立指数对账与 QuantStats 报告。M3 已冻结标签/预测契约、版本化配置、模块骨架、四段式 Agent 交付流程和 G0–G9 验收矩阵；C0、E3 严格 Receipt、G1-B2A/P1/P2/P3/P4A/P4B/P4C 代码子包及 G0 Python 兼容子项已通过主 Agent 最终验收，B4/G1 与 G0–G9 Gate 仍未关闭。`py312` 已验收 Qlib 0.9.7 兼容性且 base 未变；真实链路仍受 `CSI300_PIT` 长期数据、BaoStock smoke 和支持内核发布证据约束，详见[路线图](项目实施路线图.md)。研究阶段可使用本地 ignored Tushare token，启用实盘前必须轮换。统一回测器也仍需把股票 T+1、显式停牌/涨跌停状态和费用规则原语接入日频模拟器。

## M2 基线策略（评估完成，市场规则补齐中）

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
QuantStats 是 `research` 可选依赖，不进入交易运行时依赖。ETF 涨跌停拒单和券商
费率校准仍属于统一回测器后续项；
S0 的数据与收益口径由下述独立指数检查验收。

独立指数校验使用中证指数官方 2026-03-31 事实表的沪深300 YTD `-3.89%`。
BaoStock 同期收盘计算为 `-3.8854%`，绝对误差 `0.0046%`，通过配置中的
`0.01%` 容差。2026-01-06 至 2026-07-10，`510300.SH` 总回报与沪深300
日收益相关系数 `0.9948`、年化跟踪误差 `1.90%`；成本后账户收益 `1.975%`，
指数价格收益 `1.305%`，净差 `0.670%`。价格除息、现金分红和成本已分层，分解
残差为 0。报告位于 `artifacts/research/m2/s0_reconciliation/`。

---

本项目不构成投资建议。实盘规则、费用和权限以交易所及开户券商最新文件为准。
