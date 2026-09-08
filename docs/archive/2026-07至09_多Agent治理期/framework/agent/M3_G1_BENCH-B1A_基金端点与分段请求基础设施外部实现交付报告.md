# M3 G1 BENCH-B1A：基金端点与分段请求基础设施外部实现交付报告

日期：2026-07-22  
任务书：[`M3_G1_BENCH-B1A_基金端点与分段请求基础设施任务单.md`](M3_G1_BENCH-B1A_基金端点与分段请求基础设施任务单.md)  
角色：全新外部实现 Agent（`cursor-grok-4.5-high`）  
状态：实现与 Windows 自测完成；**未宣布 Gate 通过**；等待独立外部初验与主 Agent 终验

## 1. 改动摘要

仅白名单内新增 `fund_daily` / `fund_adj` / `fund_div` 请求基础设施；未切换 `H00300.CSI` planner、mapper、candidate、release 或 label identity；未真实调用 Tushare。

| 文件 | 目的 |
|---|---|
| `src/quant/data/connectors/tushare.py` | 新增 `fetch_fund_{daily,adj,div}_raw`；六位 `.SH/.SZ`、date 类型与反向区间在 SDK 前拒绝；fields 原样透传 |
| `src/quant/data/m3_backfill.py` | 注册三 endpoint 的 fields/policy/sort keys；`_fetch` 显式 dispatch；`plan_fund_adj_requests` 四自然年分段；policy 集合扩至十 endpoint |
| `src/quant/research/m3/config.py` | 冻结 `fund_daily=5000`、`fund_adj=2000`、`fund_div=5000`；字段闭包 138→141 |
| `src/quant/research/m3/g1_planning.py` | 三 endpoint 纳入 `_EMPTY_REJECT` 精确 policy；benchmark planner 仍输出 `H00300.CSI`，不发射基金请求 |
| `configs/research/m3_qlib_example.toml` | 同步 row-limit |
| `tests/unit/test_tushare_connector.py` | 精确参数、非法输入、fields 不重排、十 endpoint 行序保留 |
| `tests/unit/test_m3_backfill_requests.py` | 分段反例、空/截断、恶意 spec、旧七 policy fail-closed、原七 endpoint 身份回归 |
| `tests/unit/test_m3_config.py` | 闭包计数与 fund row-limit 字面量 |
| `tests/unit/test_m3_g1_planning.py` | 十 endpoint policy；benchmark 不变 |

## 2. 合同映射

| 冻结合同 | 实现 |
|---|---|
| fields 精确值 | `TUSHARE_FIELDS` 三键与任务书逐字一致 |
| policy | `(5000,REJECT)/(2000,REJECT)/(5000,REJECT)` 写入 `ENDPOINT_POLICIES_V1` 与配置 literal |
| 参数键 | `fund_daily/fund_adj`：`fields,ts_code,start_date,end_date`；`fund_div`：`fields,ts_code` |
| 代码域 | 仅六位 `.SH/.SZ`；bool/空/HK/CSI/非六位/非 date/反向日期 IO 前拒绝 |
| `plan_fund_adj_requests` | 首段至 `min(end, start.year+3-12-31)`，后续自下一自然年 1/1；连续无重叠严格递增；段长 ≤1461 |
| `_fetch` | 显式三分支，无动态方法名 |
| 旁路禁止 | 复用既有 request_id/batch/stable hash/raw/journal/错误分类 |
| planner 不变 | `plan_history_requests` 仍只发原七类 HISTORY + `index_daily` |

## 3. 自测证据（Windows Miniforge）

解释器：`D:\Miniforge3\python.exe`（反馈环；**非** WSL Gate 终验）

```text
pytest tests/unit/test_tushare_connector.py tests/unit/test_m3_backfill_requests.py tests/unit/test_m3_config.py tests/unit/test_m3_g1_planning.py -q
→ 267 passed, 12 skipped

ruff check <白名单八文件>
→ All checks passed

mypy <四生产文件>
→ Success: no issues found in 4 source files
```

未执行真实网络、未读取 token、未改 B0 raw / HISTORY journal / 路线图。

## 4. 未决风险 / 边界

- Linux/WSL Miniforge `base` Gate 终验由主 Agent 执行；本报告 Windows 绿测不代替平台终验。
- 本包未接入 benchmark 切换、mapper、总回报公式或正式 HISTORY 闭包；后续 B1B+ 负责。
- `fund_daily` 与 `daily` 的 fields 字符串相同但 endpoint 身份独立；不得混用 request_id。
- 配置字段闭包与 g1/full 身份哈希因新增三 row-limit 键而变化；既有 HISTORY receipt 未改写。

## 5. 明确非声明

**不宣布 B1A / G1 / M3 Gate 通过。** 仅交付实现与自测证据，供独立初验与主验。
