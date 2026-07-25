# M3 G1 BENCH-B1A：基金端点与分段请求基础设施主 Agent 最终验收报告

日期：2026-07-22  
结论：**B1A 子包通过主验**；不宣布 G1/M3 Gate，不代表正式 benchmark HISTORY 已抓取。

## 1. 职责闭环

- 冻结任务：[`M3_G1_BENCH-B1A_基金端点与分段请求基础设施任务单.md`](M3_G1_BENCH-B1A_基金端点与分段请求基础设施任务单.md)
- 外部实现：[`M3_G1_BENCH-B1A_基金端点与分段请求基础设施外部实现交付报告.md`](M3_G1_BENCH-B1A_基金端点与分段请求基础设施外部实现交付报告.md)
- 外部独立初验：[`M3_G1_BENCH-B1A_基金端点与分段请求基础设施外部独立初验报告.md`](M3_G1_BENCH-B1A_基金端点与分段请求基础设施外部独立初验报告.md)
- R1 行尾返工完成独立复验：
  [`M3_G1_BENCH-B1A-R1_CRLF行尾污染外部独立复验报告.md`](M3_G1_BENCH-B1A-R1_CRLF行尾污染外部独立复验报告.md)
- R2 Unicode 数字返工完成独立复验：
  [`M3_G1_BENCH-B1A-R2_Unicode数字代码越层外部独立复验报告.md`](M3_G1_BENCH-B1A-R2_Unicode数字代码越层外部独立复验报告.md)

实现、完整初验、两轮返工实现和对应复验均由不同的全新外部 Cursor 上下文承担；主 Agent 最后复核合同并
执行 WSL 权威验证。

## 2. 主验结论

- `fund_daily/fund_adj/fund_div` fields、参数、row-limit、空/截断策略和响应稳定排序与冻结合同一致；
- connector 三个 raw 方法只接受六位 ASCII `[0-9]` 加 `.SH/.SZ`，日期和代码均在 SDK 前验证；
- `fund_adj` 按至多四个自然年确定性分段，连续、无重叠、每段不超过 1461 天；
- `_fetch` 使用显式 endpoint dispatch，复用既有 request/receipt/raw/journal 闭包；
- endpoint policy 精确扩为十项，旧七 endpoint request identity 与当前 `H00300.CSI` planner 输出未改变；
- 配置和 example TOML 同步增加三个 row-limit；没有真实 Tushare 调用，没有改写既有 HISTORY receipt。

## 3. 主验发现与返工闭环

### R1：Windows 写回造成 CRLF 污染

现象为 WSL `git diff --check` 报新增行 trailing whitespace；根因是单个测试文件被整文件转换为 CRLF。
返工只做 CRLF→LF，规范化 SHA-256 精确匹配，独立复验补充 round-trip 反例。回归规则是跨平台写回后必须
执行 WSL whitespace Gate。

### R2：Unicode 数字越层

主 Agent 未公开反例证明 `str.isdigit()` 接受全角 `５１０３００.SH` 并进入 fake SDK，而 backfill ASCII
正则拒绝。返工把 connector 收紧到相同 ASCII 集合，并新增全角、Arabic-Indic 测试；独立复验再加入
Devanagari 数字，三个 endpoint 均 `calls=0`。这恢复了跨层标识接受集合一致性。

## 4. 最终验证

WSL `/home/mabw/miniforge3/bin/conda run -n base`：

```text
pytest 四个 B1A 定向文件 → 282 passed, 376 warnings
ruff check 白名单生产/测试 → All checks passed
mypy --no-incremental --cache-dir /tmp/quant-mypy-b1a-main-r2 四个生产文件
→ Success: no issues found in 4 source files
git diff --check → exit 0
```

Warnings 均来自 Pandera/Polars 已知弃用提示，不是本包新增失败。

## 5. 状态与下一步

B1A 前置已关闭，允许开始
[`M3_G1_BENCH-B1B_510300总回报映射与全链身份重基线任务单.md`](M3_G1_BENCH-B1B_510300总回报映射与全链身份重基线任务单.md)
的外部实现。只有 B1B 也完成实现—初验—主验后，才允许执行五个正式 510300 benchmark HISTORY 请求。

