# M2-SOURCE-R10：旧 Source Run 后继重建任务单

日期：2026-08-16（Asia/Shanghai）

状态：运行与本地验真完成；待统筹 canonical retain、合流与 FWD base 下发

执行者：主 Agent（外部 Agent 暂停；不另设独立初验）

## 1. 目标与非目标

### 1.1 目标

使用当前生产入口 `quant.research.run_s1_walk_forward`，在新的隔离 worktree 中重新发布一个不可覆盖的
`LightweightResearchRunV1`，诚实替代已经丢失且不能从 Git 物理字节恢复的历史 source run
`05eee8780e8eb7679d4b5f33405ff45c4addaadbefeb449ac8d77ab7ba2bb965`。

只有同时满足下列条件，才允许称为 **same-logical-inputs / same-economic-behaviour successor**：

1. 冻结配置物理 SHA-256 精确一致；
2. 四类逻辑输入的行数与 content SHA-256 精确一致；
3. R8 冻结的策略、选择结果和经济指标逐字段一致；
4. 首发为 `reused=false`，随后同命令得到同一 `run_id` 且 `reused=true`；
5. public fresh verifier 对最终 bundle 验真通过。

### 1.2 明确非目标

- 不恢复、伪造或重签旧 `05eee...` run。
- 不把 retained `b61ae28...` 静默回绑为旧 source；其日历身份不同，只可作经济数值 oracle。
- 不修改任何源码、测试、配置、路线图、README、用户事项或共享 SSOT。
- 不修改代码 hash / EOL 语义；混合 EOL 来源债另行登记，不塞入 R10。
- 不创建 `PAPER_CANDIDATE`，不启动 forward、PAPER、账户、OMS、订单或网络请求。
- 不把产物复制到根 canonical run 目录；canonical retain 由统筹在本任务完成后执行。

## 2. 权威基线与隔离边界

- exact base：`c2b4b01a64112098c9c12c3df2146bdc392e024f`
- branch：`codex/m2-source-r10-successor`
- worktree：
  `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-source-r10-successor`
- config：`configs/research/m2_s2_volatility_target.toml`
- config 物理 SHA-256（Windows CRLF）：
  `fd2ce82c4c3772752f383c7eb4439f1b89ee46d0272be4ce369eca84fbfaa9bf`
- 根数据目录仅只读：`F:\AI_Coding\QuantitativeTrading\data`
- run 发布根仅限本 worktree：`artifacts/research/runs/<new_run_id>/`

旧 run 的报告代码 SHA-256
`c426bc2ea8034ace696274a3fe4216853ae692c78eea803d1c924d2db8786b89` 无法由运行时 HEAD
`7ef9d8e5443a96eb4e4070f0d7b1181de0ebe170` 的九个 Git blob、全 LF、全 CRLF 或 512 种逐文件
LF/CRLF 组合复算。R10 必须接受当前 exact base 自然产生的新 code identity，不得要求恢复旧 code hash。

## 3. 唯一可写范围

1. `docs/research/agent/M2_SOURCE_R10_旧SourceRun后继重建任务单.md`
2. `docs/research/agent/M2_SOURCE_R10_旧SourceRun后继重建交付记录.md`
3. `artifacts/research/runs/<new_run_id>/`
4. publisher 在同一父目录内创建的唯一原子临时目录；终态必须不存在。

所有其他路径只读。禁止 `git add -A`；最终仅精确暂存两份文档，ignored run 保留给统筹 canonical retain。

## 4. 冻结运行命令与资源合同

运行目录与 import 源必须绑定本 worktree：

```text
cwd=F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-source-r10-successor
PYTHONPATH=F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-source-r10-successor\src
```

唯一业务命令：

```powershell
D:\Miniforge3\python.exe -m quant.research.run_s1_walk_forward `
  --project-root F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-source-r10-successor `
  --config configs/research/m2_s2_volatility_target.toml `
  --data-root F:\AI_Coding\QuantitativeTrading\data `
  --artifact-root artifacts
```

资源和运行约束：

- Windows Miniforge 单实例；不启动外部 Agent。
- 进程优先级 `BelowNormal`，CPU affinity `0xF00`（CPU 8–11）。
- `POLARS_MAX_THREADS=2`、`OMP_NUM_THREADS=2`、`OPENBLAS_NUM_THREADS=2`、
  `MKL_NUM_THREADS=2`、`NUMEXPR_NUM_THREADS=2`。
- 禁止网络；根 `data/` 只读。
- 两次 runner 严格串行；首发未自然终态前不得启动第二实例。
- stdout/stderr 写入 worktree 外的系统临时日志；日志读取后精确清理。

## 5. 四项逻辑输入硬判据

摘要生产算法必须使用现有 `lightweight_run.py`：对非空 DataFrame 按冻结 key 排序，序列化
`[columns, dtypes, canonical rows]` 为 UTF-8 canonical JSON（键排序、无多余空格、禁止 NaN），再取 SHA-256。
不增加另一套摘要实现。

| 输入 | 排序键 | expected rows | expected content SHA-256 |
|---|---|---:|---|
| bars | `trade_date, symbol` | 9361 | `ed84b83bd079e3e71f23ce84ff93f3c7911481b1bf5f7fa559355709031bc3a6` |
| calendars | `market, date` | 26128 | `f7e8406644a623dda8a4dfd457e1c6d8392cb56e24355602acc4156f820f10af` |
| instruments | `symbol` | 11 | `a73db18b61c192366f11df4c9541ebb35039f528f64321fdc051a9a4925bff8b` |
| research-prices | `trade_date, symbol` | 9361 | `df0367fe6569b6796dc4646a2b806a8399e3c5e7dc9ced05beaf9bf64e9e0128` |

数据选择也不得改变：

- bars：候选证券、`2023-01-01..2026-07-10`；2026 年前只用 `akshare`，此后只用 `baostock`；
- research prices：候选证券、`TOTAL_RETURN_DIVIDEND`、相同日期范围；
- calendars：SH/SZ 两份 clean calendar 全量拼接，不另做日期截断；
- instruments：SH/SZ 拼接后只保留候选证券。

任一项不等时，允许保留本次不可覆盖 bundle 作为 **new-input successor** 审计证据，但必须立刻停止：

- 不得声称同逻辑输入恢复；
- 不得执行第二次 `reused=true`；
- 不得启动 M2-FWD-R1；
- 不得通过修改 TOML、EOL、数据或摘要来掩盖差异。

retained `b61ae28...` 的 calendars 为 `8766 / 2321945d...`，明确不满足本表，禁止替代。

## 6. R8 经济行为逐字段 oracle

固定策略合同：

```json
{
  "lookback_observations": 60,
  "annualized_volatility": 0.12,
  "annualization_sessions": 252,
  "leverage_allowed": false,
  "conclusion": "RESEARCH_ONLY"
}
```

选择结果：

```json
{
  "fold_1": {"regression_window": 60, "top_k": 1},
  "fold_2": {"regression_window": 60, "top_k": 2}
}
```

未舍入经济值：

```json
{
  "aggregate_1x_compounded_test_return": 0.08545041975271306,
  "fold_1": {
    "return_0_5x": 0.03837419327600622,
    "return_1x": 0.0373321312289252,
    "return_2x": 0.03525283091899989,
    "max_drawdown_1x": -0.04928508525680875,
    "annualized_volatility_1x": 0.11186267099640367,
    "one_way_turnover_on_initial_cash_1x": 0.8334117421499998,
    "trade_count_1x": 6.0
  },
  "fold_2": {
    "return_0_5x": 0.048111196608212614,
    "return_1x": 0.04638657868120033,
    "return_2x": 0.04296052446050003,
    "max_drawdown_1x": -0.040095702140027334,
    "annualized_volatility_1x": 0.10346366863373142,
    "one_way_turnover_on_initial_cash_1x": 1.3554874376,
    "trade_count_1x": 7.0
  }
}
```

任一策略字段、选择字段或经济值不等时，保留 bundle 作差异审计并停止；不得称为同经济行为 successor，
不得执行 reuse 或 FWD。

## 7. 发布、复用与 fresh verify

1. 首次运行前确认 branch/HEAD/clean、config SHA、唯一 Python 实例和无目标 run 临时目录。
2. 首次运行必须成功返回新 `run_id` 且 `reused=false`。
3. 读取并 fresh 验证 bundle；核对四项输入和全部 R8 oracle。
4. 只有第 3 步全部精确一致，才以完全相同命令顺序执行第二次。
5. 第二次必须返回同一 `run_id`、同一路径且 `reused=true`。
6. 再调用 public verifier：

```python
from pathlib import Path
from quant.research.lightweight_run import verify_lightweight_research_run

verified = verify_lightweight_research_run(run_root=Path(r"<run-root>"))
```

public verifier 必须检查 canonical `run.json`、exact tree、root 名、每个输出 size/SHA-256、链接/实体别名和
扫描前后稳定性。失败稳定为 `LIGHTWEIGHT_RESEARCH_RUN_INVALID`。

本任务不复制 canonical 产物。统筹后续执行 no-clobber retain 时，应先验 source、目标不存在才复制、复制后再
验目标并逐文件比较相对路径/size/SHA；不得编辑 `run.json`。

## 8. 停止条件与故障处置

任一条件命中立即停止扩大动作并保留证据：

- config SHA、HEAD、工作树或命令与冻结值不符；
- 出现网络请求、根数据写入或白名单外项目写入；
- CLI 非零、stderr 非空、stdout 无法解析或进程承载状态不明；
- 首发不是 `reused=false`；
- 四项逻辑输入或 R8 oracle 任一不等；
- conclusion 不是 `RESEARCH_ONLY`；
- public verifier 失败；
- 第二次不是同 run id / 同路径 / `reused=true`；
- 同名目标已经存在但 bytes 不同；
- 发现第二个 R10 Python writer、未知临时目录或资源约束失效。

失败时不覆盖、不删除已发布的不可变 run；仅清理本次 publisher 已证明拥有且仍为原身份的临时目录和系统
临时日志。未知文件、身份漂移或并发写入时保留现场并上报，不做递归删除。

## 9. 验收与交付

- 交付记录：`docs/research/agent/M2_SOURCE_R10_旧SourceRun后继重建交付记录.md`
- 只回报 source 相对路径、run id、exact files/bytes/hash、输入/oracle逐项比较、两次 reuse 语义、public
  verify 结果、临时目录/进程/资源终态。
- 交付后只精确 stage 两份文档并形成安全提交；ignored run 保留，等待统筹 canonical retain 与合流回归。
- 不声明 PAPER_CANDIDATE、FWD、PAPER 或任何更高 Gate 通过。
