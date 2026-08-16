# M2-EVAL-R12 评估样本与持仓漂移修复任务与交付记录

## 1. 状态

- 状态：实现与定向开发检查完成；本提交形成安全点，待统筹合流。
- Owner：策略开发 session。
- Exact base：`19e937487258a41f0876cbccf97e22fc020d7692`。
- Branch：`codex/m2-eval-r12-outcome-drift`。
- Worktree：`artifacts/dev_worktrees/m2-eval-r12-outcome-drift`。
- 本包只关闭 `M2-EVAL-STOP-001` 的 A/B；C、D、分组单调性和财务版本链仍开放。

## 2. 现象、根因与系统不变量

### 2.1 A：未来 outcome 改变评价 cohort

现象：`evaluate_factor_period` 在计算 factor rank 和 group 前先过滤未来 label 与逐证券 exit；未来
outcome 缺失会改变 RankIC、group 和 validation direction。

根因：信号时点 cohort 与事后 outcome pairing 没有分层。

必须恢复的不变量：

1. signal cohort、factor rank 和 group 只由当时有限 factor 与日期级 horizon plan 决定；
2. RankIC 可在 paired labels 内另行排名，但不能重排 full cohort 的 group；
3. 每个非尾部预注册日期必须显式返回；坏日期不得被静默删除；
4. `daily_ic.n_symbols` 与 `group_returns.n_symbols` 保持旧语义，表示 paired-label count；
5. additive coverage evidence 必须区分 factor count 与 paired count。

### 2.2 B：换手未使用持有期后漂移权重

现象：模拟器把上期 target 直接当作下期交易前持仓；即使个股收益不同，target 不变时也可能错误得到
零换手、零调仓成本。末端清仓同样使用未漂移 target。

根因：内部 period 只有组合均值，无法恢复逐证券持有期后权重。

必须恢复的不变量：

1. future outcome 只通过内存 `holding_outcomes(as_of,symbol,holding_return)` 进入模拟器；
2. targets、periods、publisher 与 `run.json` 不得携带该 future outcome；
3. gross return 由 current target weights 与 chosen holding returns 重算并与 period 值核对；
4. 下一期换手和 terminal sell 必须使用收益后漂移权重；
5. 缺失、重复、非有限、低于 -100% 的证券收益、非正组合 gross factor、非连续持有期与非法权重均
   fail-closed。

组合 gross 的重复计算与 period 投影采用固定绝对容差 `1e-12`；该容差只处理 Float64/Decimal 投影，不能
吸收经济数据差异或被结果后调整。

## 3. 冻结接口与证据列

`evaluate_factor_period` 保持参数和三元返回结构。旧列保留，新增：

- `factor_count`
- `paired_count`
- `coverage_numerator`
- `coverage_denominator`
- `coverage_status`

`daily_ic` 成功行的 status 为 `PASS`。`group_returns` 形成完整 `date × group` grid；有 paired label 的组为
`PASS`，空 paired 组显式保留为 `NO_PAIRED_LABELS`，空 factor 组为 `EMPTY_FACTOR_GROUP`，mean 可为空。

`simulate_diagnostic_factor_portfolio` 新增必填 keyword-only `holding_outcomes`。该长表只在调用栈内存中
使用，不进入返回结果或任何不可变研究产物。

## 4. 关键反例

1. 101 证券中未入 Top-K 的一只 label 缺失：factor cohort/group 不变，paired coverage 显式下降；
2. paired count 低于 `minimum_symbols`、IC 非有限、同日 mixed/null/multiple exit 或内部 horizon 缺口：
   整次稳定拒绝；
3. 连续两期 A/B target 均 50%/50%，首期收益为 +100%/0%：下一期交易前权重为 2/3、1/3，L1
   turnover 必须为 1/3；
4. 未选择证券收益变化不得改变 targets 或 NAV；
5. terminal sell 使用最后持有期漂移权重；
6. chosen outcome 缺失、重复、NaN/Inf、低于 -100%，组合 gross factor 非正，或持有期重叠/留空档：
   稳定拒绝。

## 5. Exact 白名单

1. `src/quant/research/classic_factor_evaluation.py`
2. `src/quant/research/run_classic_factors.py`
3. `src/quant/research/classic_factor_composite.py`
4. `src/quant/research/classic_factor_model.py`
5. `tests/unit/test_classic_factor_evaluation.py`
6. 本文件
7. `docs/roadmaps/M2_策略与因子库并行建设路线图.md` 的本包状态/evidence hunk

禁止修改 runner main、PIT/daily config、Schema、publisher、repository、facade、`pyproject.toml` 或任一
共享 IO 合同。本包不得顺手关闭成本配置 provenance/semantic identity；该项由后续独立
`M2-COST-R13` 关闭。

## 6. 开发检查

资源边界：唯一 Python 实例、BelowNormal、affinity `0xF00`、数值线程不超过 2；不做真实 run、全量
pytest 或 data I/O。

顺序：

1. `tests/unit/test_classic_factor_evaluation.py`
2. `test_run_classic_factors.py`、`test_run_daily_value_factors.py`、`test_run_pit_quality_factors.py`、
   `test_classic_factor_composite.py`、`test_run_classic_factor_composite.py`、`test_classic_factor_model.py`、
   `test_run_classic_factor_model.py`
3. Ruff：四个生产文件与主测试
4. mypy：四个生产文件
5. fresh cold imports

## 7. 历史证据边界

R11 登记的 13 个 immutable run 不回写、不重签、不批量重跑。A 使其 IC/group/方向派生证据不得用于
promotion；B 使其 turnover/cost/NAV/成本压力证据失效。四个 HOLD 继续禁止晋级，九个 REJECTED 不翻案，
但成本主导拒绝不能继续表述为有效经济证伪。

## 8. 交付证据

### 8.1 实现结果

- A：因子 cohort、rank 和 group 在 outcome pairing 前冻结；paired RankIC 在 paired 子样本内另行排名，
  并输出不改变旧 `n_symbols` 语义的 additive coverage evidence；非尾部坏日期稳定拒绝。
- B：三个上层调用点仅在内存构造 `holding_outcomes`；模拟器逐期重算 gross、核对 period，并把收益后漂移
  权重用于下一次换手和 terminal sell。未选择证券 outcome 不参与闭包。
- 对外不可变 outputs、publisher 和 `run.json` schema 均未改变；没有真实 run、数据读取或历史 artifact
  回写。

### 8.2 开发检查证据

所有可计检查使用 Windows 原生 `D:\Miniforge3\python.exe`，唯一前台进程，BelowNormal、CPU8—11
(`0xF00`)，数值线程不超过 2。

1. focused 首轮 `26 passed, 1 failed`；失败是测试仍把已调整后的正常 `exit_date` 当作非法值，修正测试
   输入后最终 `27 passed, 55 warnings in 3.40s`；
2. 七文件邻接首轮 `45 passed, 1 failed`；失败暴露既有 composite 诊断允许
   `execution_date == exit_date`，最小修正为只拒绝逆序，最终
   `46 passed, 495 warnings in 7.85s`；
3. Ruff（四个生产文件与主测试）：`All checks passed!`；
4. mypy（四个生产文件）：`Success: no issues found in 4 source files`；
5. fresh isolated cold import：`M2_EVAL_R12_COLD_PASS`；
6. `git diff --check` 通过，仅有工作树 LF→CRLF 提示；本包测试临时目录均不存在，未残留
   `0xF00` Python 进程。

Pandera/Polars deprecation warning 为既有 warning，不是本包失败。上述证据只关闭
`M2-EVAL-STOP-001` 的 A/B；C、D、20 日分组单调性、PIT 版本链和 audit-v4 仍为后续硬前置。
