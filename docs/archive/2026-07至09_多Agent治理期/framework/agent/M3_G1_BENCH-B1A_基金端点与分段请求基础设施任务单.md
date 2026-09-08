# M3 G1 BENCH-B1A：基金端点与分段请求基础设施任务单

## 1. 目标

为已确认的 `510300.SH` ETF benchmark 路线建立可复用、不可变的 Tushare 请求基础设施。本包只新增
`fund_daily/fund_adj/fund_div` endpoint、连接器、配置 row-limit 与确定性 `fund_adj` 分段 helper；暂不切换
当前 `H00300.CSI` planner、mapper、candidate、release 或 label identity，保证本包可独立绿测和独立初验。

实现与初验必须由两个全新的外部 Cursor 会话承担，模型均使用 `cursor-grok-4.5-high`。实现者不得宣布
Gate 通过；初验者除唯一报告外只读。

## 2. 权威事实与冻结合同

- 真实 B0/R1 raw 证据见
  [`M3_G1_BENCH-B0_510300ETF基准源探针与合同冻结任务单.md`](M3_G1_BENCH-B0_510300ETF基准源探针与合同冻结任务单.md)。
- fields 精确值：
  - `fund_daily`：`ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount`
  - `fund_adj`：`ts_code,trade_date,adj_factor`
  - `fund_div`：`ts_code,ann_date,imp_anndate,base_date,div_proc,record_date,ex_date,pay_date,earpay_date,net_ex_date,div_cash,base_unit,ear_distr,ear_amount,account_date,base_year`
- endpoint policy：`fund_daily=(5000,REJECT)`、`fund_adj=(2000,REJECT)`、
  `fund_div=(5000,REJECT)`。`fund_div` 的 5000 是项目保守上限；正式 benchmark 已知有 22 行实施记录。
- `fund_daily` 和 `fund_adj` 参数精确为 `fields,ts_code,start_date,end_date`；`fund_div` 参数精确为
  `fields,ts_code`。三者只接受六位 `.SH/.SZ` 可交易基金代码。
- `plan_fund_adj_requests(symbol,start,end)`（名称可按现有风格微调）按不超过四个完整自然年分段：首段从
  `start` 到 `min(end, start.year+3-12-31)`，后续从下一自然年 1 月 1 日开始；区间连续、不重叠、严格
  递增。每段最多 1461 个自然日，因此不可能触及 2000 行上限。
- request_id、batch hash、stable response hash、raw/journal/no-clobber 和错误分类沿用现有 B2A 合同；不得
  为基金 endpoint 建第二套旁路。
- `_fetch` 必须显式 dispatch 到新增的 connector raw 方法，不使用动态任意方法名。

## 3. 文件白名单

生产/配置：

- `src/quant/data/connectors/tushare.py`
- `src/quant/data/m3_backfill.py`
- `src/quant/research/m3/config.py`
- `src/quant/research/m3/g1_planning.py`
- `configs/research/m3_qlib_example.toml`

测试：

- `tests/unit/test_tushare_connector.py`
- `tests/unit/test_m3_backfill_requests.py`
- `tests/unit/test_m3_config.py`
- `tests/unit/test_m3_g1_planning.py`

报告：

- `docs/framework/agent/M3_G1_BENCH-B1A_基金端点与分段请求基础设施外部实现交付报告.md`

除上述文件外只读。`g1_planning.py` 只允许把新增三 endpoint 纳入精确 policy 集合并保持当前 benchmark
planner 输出不变。不得修改 B0 raw、既有 HISTORY journal/receipt、`m3_g1_candidate.py`、`m3_mappers.py`、
`m3_release.py`、当前 benchmark 配置值或路线图。

## 4. 必测反例

- `bool`、空代码、HK/CSI/非六位代码、反向日期和非 date 输入在任何 IO 前拒绝；
- 分段恰跨 12/31、闰年、单日、恰好四年和四年以上，证明无重叠/空洞且稳定排序；
- fake client 收到精确参数与 fields；目标外列顺序不得被 connector 偷改；
- 空 `fund_daily/fund_adj/fund_div` 按各自 policy 拒绝；恰好 row_limit 也按现有“可能截断”规则拒绝；
- 恶意 caller-owned spec、policy 缺键/多键、旧七 endpoint policy 均 fail closed；
- 原有七 endpoint 的 request_id、planner 输出、fetch dispatch 和测试行为保持不变。

## 5. 验收命令

Windows PowerShell 7 可作反馈环；最终以 WSL Miniforge `base` 为准：

```bash
python -m pytest tests/unit/test_tushare_connector.py tests/unit/test_m3_backfill_requests.py tests/unit/test_m3_config.py tests/unit/test_m3_g1_planning.py -q
ruff check src/quant/data/connectors/tushare.py src/quant/data/m3_backfill.py src/quant/research/m3/config.py src/quant/research/m3/g1_planning.py tests/unit/test_tushare_connector.py tests/unit/test_m3_backfill_requests.py tests/unit/test_m3_config.py tests/unit/test_m3_g1_planning.py
mypy src/quant/data/connectors/tushare.py src/quant/data/m3_backfill.py src/quant/research/m3/config.py src/quant/research/m3/g1_planning.py
```

交付报告只给压缩摘要：改动、合同映射、测试结果、未决风险；不回传完整日志或任何 token。
