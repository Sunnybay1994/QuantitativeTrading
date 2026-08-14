# M2 DATA R1：Tushare 核心历史 Raw 数据质量审计

日期：2026-08-14（Asia/Shanghai）  
结论：**采集自然完成，raw 发布闭包完整；存在必须在 clean 准入前隔离的上游历史异常，当前不得把整批 raw 直接视为 clean。**

## 1. 审计范围与用途

本审计只读检查共享数据根
`F:\AI_Coding\QuantitativeTrading\data` 下的 `daily`、`adj_factor` 和
`fund_daily` 核心历史采集。检查目标是回答两件事：

1. 后台采集是否自然完成，账本、文件和内容摘要是否闭合；
2. 这些不可变 raw 是否已经具备进入标准化和策略研究的最低质量条件。

本审计不修改 raw、不自动重启采集、不执行 clean 发布，也不把 raw 的完成状态等同于某个策略已在新数据上验证。

## 2. 采集自然终态

- SQLite ledger：`COMPLETE=24,343`，其余状态均为 0；
- 后台采集进程已自然退出；
- stderr 文件为 0 字节；
- 24,343 个完成请求均存在 `data.parquet + metadata.json`，无缺失、无额外 request 目录；
- metadata 的 request id、行数、文件大小和 SHA-256 与 ledger 全部一致；
- 重新读取 24,343 个 Parquet 文件并计算 SHA-256，差异数为 0。

| 数据集 | 请求/文件 | 数据行 | 空结果请求 | 最大单次行数 | Parquet 字节 |
|---|---:|---:|---:|---:|---:|
| `daily` | 8,704 | 18,107,780 | 1 | 5,540 | 618,637,098 |
| `adj_factor` | 8,704 | 18,935,088 | 0 | 5,557 | 101,707,430 |
| `fund_daily` | 6,935 | 3,145,969 | 56 | 2,104 | 140,417,623 |
| 合计 | 24,343 | 40,188,837 | 57 | — | 860,762,151 |

没有请求达到冻结的最大行数上限，ledger 中没有 `FAILED`、`RETRYABLE` 或 `SPLIT_REQUIRED`。

## 3. 全量内容质量

全量扫描使用 DuckDB `threads=2`，避免占满开发机 CPU。检查了预期粒度
`(ts_code, trade_date)`、关键空值、正价格/复权因子、OHLC 关系、日期格式、成交量和成交额。

| 数据集 | 主键重复 | key/核心值空值 | 非正核心价格/因子 | 负成交量/额 | OHLC 关系异常 |
|---|---:|---:|---:|---:|---:|
| `daily` | 0 | 232（均为 `amount`） | 0 | 0 | 21 |
| `adj_factor` | 0 | 0 | 0 | 不适用 | 不适用 |
| `fund_daily` | 0 | 0 | 0 | 0 | 0 |

日期字段均为 8 位文本。`daily` 覆盖 1990-12-19 至 2026-08-13；`adj_factor`
覆盖至 2026-08-14；`fund_daily` 的首个非空交易日为 1998-04-07，覆盖至 2026-08-14。

## 4. 必须在 clean 前处理的异常

### 4.1 232 条股票成交额空值

232 条记录的 `amount` 为空，价格、成交量及主键不为空。其中 `000536.SZ` 有 136 条，覆盖
1993-11-30 至 1994-06-22；其余 96 条集中在 1993-12-23 的早期沪深证券。领域
`Bar1dSchema.amount` 是非空非负值，clean 构建不得把这些空值静默填成 0；应隔离并保留缺失原因证据。

### 4.2 21 条股票 OHLC 关系异常

21 条记录不满足 `low <= open/close <= high`。其中 19 条集中在 1991–1994 年早期市场数据，
另 2 条为 `920489.BJ` 的 2014 年记录。raw 必须原样保留；clean 构建应把这些行隔离并生成质量证据，
不得排序、取 min/max 或改写价格来静默“修复”。

### 4.3 尚未进入当前领域枚举的证券代码

- `daily` 含北交所代码 339,947 行、340 个证券；`adj_factor` 含对应北交所代码 556,359 行；
- `adj_factor` 另含 `T00018.SH` 共 1,506 行；
- `fund_daily` 含若干 7 位或字母尾码，例如 `1500011.SZ`、`161022A.SZ`。

当前 `SYMBOL_PATTERN` 只接纳 5–6 位的 SH/SZ/HK 代码，尚未接纳 BJ。北交所数据不是坏 raw，但在领域枚举、
交易规则和 clean Schema 明确扩展前不能进入当前 A 股 clean；历史特殊标识同样不能冒充六位 A 股/基金代码。
标准化层应先通过版本化映射/市场范围规则识别；无法证明映射的记录进入隔离区，不进入默认证券发现。

### 4.4 日线与复权因子覆盖差异

`daily` 中有 1,448 个 key 没有对应 `adj_factor`，全部属于 `600018.SH` 的
2000-07-19 至 2006-09-25。反向差异较多，主要来自停牌日仍发布复权因子，不能简单要求两表全集相等。
需要总回报价格的 clean 构建应对前一类缺口 fail closed，不能默认填充 1.0。

### 4.5 截止时点差异

`daily` 的唯一空结果请求是 2026-08-14；同日 `adj_factor` 和 `fund_daily` 已有数据。
这与采集发生在股票收盘日线发布前相符。后续增量运行应重新请求并补齐该日，当前快照的股票日线
可知截止日应明确记为 2026-08-13。

`fund_daily` 的 56 个空结果全部位于 1998-01-05 至 1998-04-06，早于首个非空基金日线，属于可解释的
前置空窗口。

## 5. 下游使用裁定

- **可用**：作为不可覆盖的 Tushare raw 基线；用于后续可重放的标准化、异常隔离和增量采集。
- **暂不可用**：未经 clean Schema、特殊代码映射、OHLC 隔离和复权覆盖门禁，不能由策略、因子或回测层直接读取。
- **不改变既有策略结论**：当前 M2 walk-forward 仍绑定既有 frozen clean 内容摘要；本批 raw 的完成不会自动更新已有 `run.json`。

因此数据采集阶段可以关闭，但 clean 发布仍需一个窄任务：以本报告列出的异常为回归样本，构建显式的
标准化与质量门禁，并由新的 run 绑定新 clean snapshot 后才能用于新增研究窗口。

## 6. 可重放 clean 准入门禁

项目现提供只读命令 `quant.data.audit_tushare_bulk_clean`。它从 SQLite ledger 派生唯一请求集合，核对
request 目录、metadata、行数、大小和可选 Parquet SHA，再以受限 DuckDB 线程扫描全量主键、空值、价格、
OHLC、证券代码与 `daily`/`adj_factor` 覆盖。它只生成 `READY` 或 `BLOCKED` 证据，不执行 clean 发布。

```powershell
$env:PYTHONPATH = 'src'
python -m quant.data.audit_tushare_bulk_clean `
  --data-root data --threads 2 `
  --output artifacts/data_quality/tushare-bulk-clean-admission-20260814.json
```

开发机已有逐文件 SHA 闭包证据时，可加 `--skip-byte-verification` 避免重复读取 860 MB；正式独立复核仍应
省略该选项。命令返回 0 表示 `READY`，返回 3 表示审计正常完成但准入被阻断；输入、目录或来源闭包无效则
抛出稳定错误，不把异常数据当作普通质量问题继续运行。

本次真实全量运行返回 `BLOCKED`，审计产物为
`artifacts/data_quality/tushare-bulk-clean-admission-20260814.json`，SHA-256 为
`F75568F131717995F1FFC506FAAE75A611B7E9FE53901F9785EF4ED2A5CF8B61`；其
`raw_snapshot_sha256=78d664f6cd4820659ea5378e252124c45d7467ef161737dd05fb60a1d6d8e61d`。
