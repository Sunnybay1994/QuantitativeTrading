# M3 G7D-F1 R1 正式 A 股开盘执行事实独立初验报告

日期：2026-08-09

角色：未参与实现的全新独立初验 Agent

结论：**PASS；仅表示 G7D-F1 R1 独立初验通过，可进入主 Agent 最终验收**

边界：本结论不等于主 Agent 最终验收、完整 G7D/G7/M3、真实全 work、真实数据/账户、实盘或
Linux/ext4 Gate 通过。

## 1. 范围、前置与只读纪律

- 完整阅读了 `AGENTS.md`、`.ai` 通用规则、G7D-F1 R1 任务单、实现交付报告、
  `src/quant/backtest/a_share_execution.py`、`src/quant/backtest/__init__.py`、F1 新增测试，以及
  G7D-F0 exact capability 的 production、测试和冻结合同。
- 核对 G7D-F0 R3 与 G7C R3 的独立复验、主 Agent 最终验收报告：两项前置均明确 **PASS**，G7C 主验报告
  明确允许进入 G7D-F1；未触发任务单停止条件。
- production、实现测试、任务单和交付报告全程只读；未联网、未访问真实数据或账户、未 add/commit。
  本轮唯一仓库写入是本报告。测试临时目录和 mypy cache 均放在系统临时目录，并禁用 pytest 仓库 cache
  与 Python bytecode 写入。

## 2. 合同逐项映射

| 冻结合同 | 独立证据 | 结论 |
|---|---|---|
| exact public API 与 formal/development 隔离 | 两个 formal 入口签名与任务单一致；入口先检查 exact facts/date/tuple/str 和严格字典序。独立 hostile fake、subclass、development facts、裸 DataFrame 均在零 property access 前稳定拒绝。既有 development API 未重签或包装为 formal。 | PASS |
| F0 fresh 消费顺序与 exact capability | 首次 facts 消费为 `identity`，随后只通过 F0 property 取得 clone；F0 issued-instance、whole-content HMAC、provenance、reload 隔离和唯一完整 public loader 合同保持不变。固定顺序探针双平台通过。 | PASS |
| 日期、symbol、instrument、生命周期与潜在持仓域 | date 只从 `H00300.CSI` benchmark key 域验证；symbol 请求严格有序唯一；instrument exact 一行并检查 STOCK/CNY/SH\|SZ、suffix、格式与 inclusive 生命周期；bar XOR FULL_DAY。独立 pre-list exact issued capability 对 builder 与 rule resolver 均 fail closed。 | PASS |
| open-only 最小消费 | builder 只投影 instrument 必需字段、benchmark key、bar 的 source/open、suspension 的 source/scope/detail、limit 必需字段；未访问 calendar、corporate actions、reconciliation 或账户/target/label。独立改变 `amount` 并把 CA/reconciliation property 设为爆炸访问后，输出仍逐字段等于 baseline，且禁止属性零访问。 | PASS |
| FULL_DAY、PARTIAL 与缺事实语义 | FULL_DAY 必须无 bar，允许 0/1 limit，固定输出无 open、双拒、`SUSPENDED`；bar+FULL_DAY、非 FULL_DAY 缺 bar/limit 均拒绝，不产生 formal `MISSING_OPEN` 成功行。PARTIAL 使用 exact `" | "` 和 09:30 半开区间，未知文本保守双拒。 | PASS |
| limit/open Decimal 边界 | 非 FULL_DAY 要求 exact 一条 `has_price_limit=true` 且上下限 finite positive；比较使用 `Decimal(str(value))` 与 0.01 元 tick 的半 tick 含等号边界。实现测试的半 tick 内/等于/刚超过矩阵与双平台定向组均通过。 | PASS |
| formal 数量规则 | 规则先经过同一 facts/date/symbol/instrument/潜在持仓域窄重验，再复用唯一 `AShareOrderQuantityRule`。独立 formal STAR 请求得到 200/1 买卖规则和 exact `sse_szse_limit_order_quantity_v1`；主板/创业板邻接测试通过。入口未接收持仓、未生成 intent/fill/rejection。 | PASS |
| 输出 Schema、顺序、clone 与下游边界 | 精确 12 列、dtype、唯一 `(date,symbol)`、物理顺序和 `OpenExecutionStateSchema` 返回前重验；空 tuple 返回精确空 Schema。返回普通 DataFrame 可由 caller 修改而不影响 facts；当前 formal public 下游没有 `open_states` 裸帧入口。 | PASS |
| 稳定错误、异常图与零副作用 | 所有 public 失败统一为 exact `AShareExecutionError("M3_A_SHARE_EXECUTION_INVALID")`，在 active `except` 外 `from None`，cause/context 为空。独立递归 cause 图未泄露 hostile 文本；文件、mkdir、网络、日志探针零调用。 | PASS |
| package 与邻接兼容 | Windows 与 WSL base 的 F1/F0/development、G7C/simulator、fixed-order、Ruff、mypy、cold import 全部取得明确绿色终态；cold import 未加载 Qlib、LightGBM、MLflow。 | PASS |

静态审读未发现必须返工的问题，也未发现新增 capability、signer、mint、restore、mutable registry、generic
factory，或 F1 回调 G1/G7A/G7B verifier、formal loader、裸路径、账户、配置和 I/O 的路径。

## 3. 实现者未使用的独立临时反例

以下探针通过 stdin 运行，不写入 production/tests：

1. **`amount` 差分 + CA/reconciliation 爆炸属性**：在 open/source/limit/suspension 不变时仅把请求 bar 的
   `amount` 改为另一合法值，同时把 `corporate_actions` 与 `corporate_action_reconciliation` property 改为一旦
   访问即抛错。formal open-state 与 baseline 逐字段相同，禁止属性零访问：
   `INDEPENDENT_OPEN_ONLY_AMOUNT_CA_PASS`。
2. **pre-list 生命周期域**：对 exact issued capability 把请求证券 `list_date` 改到请求日之后；builder 与 quantity
   resolver 均只暴露稳定错误，cause/context 为空：`INDEPENDENT_PRE_LIST_DOMAIN_PASS`。
3. **更强零访问对象**：fake 与 formal subclass 的 `__getattribute__` 对任意属性均记录并抛错；与 development
   facts、裸 DataFrame 一起传入两个 formal API，全部在访问前拒绝，访问记录为空：
   `INDEPENDENT_EXACT_TYPE_ZERO_ACCESS_PASS`。
4. **FULL_DAY/limit/数量邻接**：FULL_DAY 缺 limit 仍无 open 且双拒；非 FULL_DAY 的 false/null price band
   稳定拒绝；exact formal STAR instrument/domain 解析为 200/1：
   `INDEPENDENT_FULL_DAY_LIMIT_QUANTITY_PASS`。
5. **递归 hostile 异常图**：facts `bars` property 抛出互相引用 cause 的两异常；public 边界仅保留稳定码，
   `cause/context` 均为空，格式化错误不含 hostile secret：
   `INDEPENDENT_RECURSIVE_EXCEPTION_GRAPH_PASS`。

前两项满足任务单要求的两个独立新反例：第一项证明未来/禁止事实不影响 open-only 结果，第二项证明
instrument 生命周期请求域 fail closed。其余三项用于加固 exact-type、FULL_DAY/limit/quantity 和异常图证据。

## 4. Windows Miniforge 验证

工作目录为本工作树，`PYTHONPATH` 指向本工作树 `src`。

- F1 + F0 + development facts/execution：**113 passed**，`167.32s`。
- G7C formal + development simulator：**14 passed**，`164.61s`。
- 同一 pytest 进程固定顺序 F0 → G7C → F1 → development facts/execution → G7E：
  **17 passed**，`85.99s`。
- 独立临时反例：五组全部 PASS，进程退出码 0。
- Ruff：`All checks passed!`。
- mypy：`Success: no issues found in 1 source file`。
- cold import：`WINDOWS_COLD_IMPORT_PASS`。

测试仅出现既有 Pandera/Polars `how='horizontal'` deprecation warning；没有失败或错误摘要。

## 5. WSL Miniforge base 兼容验证

通过直接 argv 调用 WSL base，明确使用工作树自身 `src`：

- F1 + F0 + development facts/execution：**113 passed**，`126.86s`。
- G7C formal + development simulator：**14 passed**，`129.35s`。
- 同一 pytest 进程 fixed-order：**17 passed**，`46.87s`。
- Ruff：`All checks passed!`。
- mypy：`Success: no issues found in 1 source file`。
- cold import：`WSL_COLD_IMPORT_PASS`。

首次旧式 `bash -lc` 承载调用在约 6 秒内无输出返回；一次只读进程检查确认没有遗留 pytest。该调用不计
通过或失败证据，修正为 direct argv 后取得上述明确终态，没有并发启动第二个测试写者。

`pwd -P` 为 `/mnt/f/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g4-formal`；`findmnt -T .`
返回 `/mnt/f F:\ drvfs`。因此 WSL 结果仅是 DrvFS 双平台兼容证据，**不是 Linux/ext4 Gate**。

## 6. Diff、范围与剩余风险

- 任务指定文件的 `git diff --check` 退出码 0；仅有工作树既有 LF/CRLF 提示，无 whitespace error。
- 本轮开始前工作树已有大量其他 M3 脏文件、未跟踪报告与旧 `.pytest-*` 目录；本轮未修改、删除或据其
  宣布其他 Gate 状态。使用系统临时目录后未新增仓库测试缓存。
- 未运行机械式全量测试；按任务单只运行 F1/F0 定向、G7C/development 邻接、fixed-order 与静态/冷导入检查。
- 未验证真实 formal 数据、真实账户、真实网络、完整 F2/G7D/G7E/G7F、正式全 work 性能或 Linux/ext4。

## 7. 最终结论

G7D-F1 R1 的 exact formal 输入、F0 fresh 链、open-only 事实投影、FULL_DAY/PARTIAL/limit、数量规则、稳定错误、
零副作用和 formal/development 邻接合同均有静态审读、实现测试、独立新反例及 Windows/WSL base 明确终态支撑。
本轮未发现阻断或返工项，故独立初验结论为 **PASS，可进入主 Agent 最终验收**。

主 Agent 仍须独立复核 SSOT、跨模块不变量、最终 diff 与验收证据；在主验明确 PASS 前，不得把 G7D-F1、
G7D、G7、M3 或 Linux/ext4 Gate 标记为完成。
