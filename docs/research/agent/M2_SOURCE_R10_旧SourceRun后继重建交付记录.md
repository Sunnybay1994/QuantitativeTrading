# M2-SOURCE-R10：旧 Source Run 后继重建交付记录

日期：2026-08-16（Asia/Shanghai）

状态：**PASS — same-logical-inputs / same-economic-behaviour successor 已发布并 fresh 验真；仍为 `RESEARCH_ONLY`。**

## 1. 结果

- exact base：`c2b4b01a64112098c9c12c3df2146bdc392e024f`
- branch：`codex/m2-source-r10-successor`
- source 相对路径：
  `artifacts/research/runs/e43da184f942286ae7e8b79aa25bc540f692cb467821003ce193c9d35fb7a96f`
- successor run id：
  `e43da184f942286ae7e8b79aa25bc540f692cb467821003ce193c9d35fb7a96f`
- conclusion：`RESEARCH_ONLY`
- config SHA-256：
  `fd2ce82c4c3772752f383c7eb4439f1b89ee46d0272be4ce369eca84fbfaa9bf`
- 当前 exact base 自然产生的 code SHA-256：
  `43cb21f58b354753a7a4a51102d05d4a671ebbb4315cc6583c3213ae08fe2bd3`

该 bundle 诚实取代已丢失的 `05eee...` source run；它不声称恢复无法保留的旧混合 EOL 物理代码字节，
也没有把 calendar 身份不同的 retained `b61ae28...` 回绑为 source。

## 2. 执行与复用证据

运行命令、cwd、`PYTHONPATH`、只读 data root 和资源参数均与任务单一致：Windows Miniforge、单实例、
`BelowNormal`、affinity `0xF00`、数值线程上限 2、无网络。

### 2.1 首发

- 第一种无回显 carrier 经 PID、日志目录和 run 目录三项核对确认从未启动，不计执行证据，也没有重试竞态。
- 唯一实际首发进程：PID `29244`；启动后实测 `BelowNormal / 0xF00` 且 CPU 增长。
- 自然退出；stderr 为 0 B；stdout 完整 JSON 给出同一 run id 与 `reused=false`。
- 首发 carrier 没有保留原生 exit code；完成 JSON、不可变 bundle、前后 public fresh verify 和随后原生
  exit 0 的同命令复用共同构成本次成功证据，不把未记录值伪写为 0。

### 2.2 复用

- 仅在输入和经济 oracle 全部通过后才执行第二次。
- 使用完全相同命令、cwd、config/data/artifact root 与资源约束。
- 原生终态：`exit=0`、stderr count `0`。
- stdout：同一 run id、同一路径、`reused=true`。
- 复用前后六文件 size/SHA-256 完全相同。

## 3. 四项逻辑输入比较

| 输入 | expected rows | actual rows | expected SHA-256 | actual SHA-256 | 结论 |
|---|---:|---:|---|---|---|
| bars | 9361 | 9361 | `ed84b83bd079e3e71f23ce84ff93f3c7911481b1bf5f7fa559355709031bc3a6` | 同左 | PASS |
| calendars | 26128 | 26128 | `f7e8406644a623dda8a4dfd457e1c6d8392cb56e24355602acc4156f820f10af` | 同左 | PASS |
| instruments | 11 | 11 | `a73db18b61c192366f11df4c9541ebb35039f528f64321fdc051a9a4925bff8b` | 同左 | PASS |
| research-prices | 9361 | 9361 | `df0367fe6569b6796dc4646a2b806a8399e3c5e7dc9ced05beaf9bf64e9e0128` | 同左 | PASS |

四项均精确闭合，因此不是 `new-input successor`。

## 4. R8 策略与经济 oracle 比较

- volatility target：`lookback=60`、`target=0.12`、`sessions=252`、`leverage_allowed=false` — PASS
- fold 1 selection：`top_k=1, regression_window=60` — PASS
- fold 2 selection：`top_k=2, regression_window=60` — PASS
- aggregate 1x compounded test return：`0.08545041975271306` — PASS

| 指标 | fold 1 expected/actual | fold 2 expected/actual | 结论 |
|---|---:|---:|---|
| 0.5x return | `0.03837419327600622` | `0.048111196608212614` | PASS |
| 1x return | `0.0373321312289252` | `0.04638657868120033` | PASS |
| 2x return | `0.03525283091899989` | `0.04296052446050003` | PASS |
| 1x max drawdown | `-0.04928508525680875` | `-0.040095702140027334` | PASS |
| 1x annualized volatility | `0.11186267099640367` | `0.10346366863373142` | PASS |
| 1x one-way turnover / initial cash | `0.8334117421499998` | `1.3554874376` | PASS |
| 1x trade count | `6.0` | `7.0` | PASS |

所有比较使用 `report.json` 原始 UTF-8 JSON 数值，不以控制台乱码后的 caveat 文本作判断。全部字段精确相等，
因此 successor 具备同经济行为证据。

## 5. Bundle 字节闭包

最终 exact tree 仅包含以下六个文件，总计 `60,597` bytes：

| 文件 | bytes | SHA-256 |
|---|---:|---|
| `report.json` | 17114 | `cbae2f083c0c8e982d164281e907136c47b0b0e843f262057def52ea53ef2d36` |
| `run.json` | 3869 | `d750ce127c23413e97f9961c976760d131df84c66d1735820793c75fb62b9de3` |
| `test_nav.parquet` | 10917 | `2cbbf582a39e18d12de234e0ba830118f3393369f750954a87f75e219b161d0e` |
| `test_target_gaps.parquet` | 19925 | `ee68e920af57852350c95e60752a62d8ec3e908af8491d59e3a73481f999a97b` |
| `test_targets.parquet` | 3189 | `eb2cbf0ee0ea272f6593f041df77ac7f3dc351818b0c61053f64560ae6ce780c` |
| `test_trades.parquet` | 5583 | `260a75f2b1d4f8e184bc8401b8e2e67f8b2a8635db031f21f71e5efae946cf5b` |

`verify_lightweight_research_run(run_root=...)` 在首发后和复用后均通过；复用后返回 exact run id。输出父目录
只有该 run 目录，没有 publisher 临时目录或第二个 run。

## 6. 清理、范围与资源终态

- 首发系统临时目录在确认归属后精确删除；其中只有 `stdout.log` 18,217 B 和 `stderr.log` 0 B。
- 不存在本次 publisher 原子临时目录。
- config SHA 和 HEAD 在运行前后不变。
- 未修改 `src/**`、`tests/**`、`configs/**`、roadmap、README、用户事项或共享 SSOT。
- ignored source run 保留在本 worktree，未复制、移动或重签到根 canonical 目录。
- 未启动网络、PAPER、账户、OMS 或订单。

## 7. 交接与剩余边界

1. 统筹应按任务书执行 canonical no-clobber retain：先验 source、目标不存在才复制、复制后再 public verify 并
   逐文件比较相对路径/size/SHA-256；本任务没有代为执行。
2. canonical retain 和证据文档合流后，才可下发 M2-FWD-R1 exact base。
3. FWD 必须绑定本 verified source run 与其 source config SHA；不得形成 forward config 自哈希循环。
4. 本结果仍是 `RESEARCH_ONLY`，不等于 `PAPER_CANDIDATE`、PAPER 准入、forward 完成或任何实盘授权。
