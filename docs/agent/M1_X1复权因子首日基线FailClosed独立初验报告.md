# M1-X1 复权因子首日基线 Fail-Closed 独立初验报告

日期：2026-07-18  
角色：外部独立初验 Agent（全新会话，未参与实现）  
任务单：[M1_X1复权因子首日基线FailClosed实现任务单.md](M1_X1复权因子首日基线FailClosed实现任务单.md)  
交付报告：[M1_X1复权因子首日基线FailClosed实现交付报告.md](M1_X1复权因子首日基线FailClosed实现交付报告.md)  
结论：**独立初验通过**；仅进入主验前置，**不宣称主验 / M1 Gate / hk_adjfactor 权限 / 真实数据链路通过**

## 0. 只读边界与方法

- 生产代码、实现者测试、任务书、配置、`data/**`、`artifacts/**`、`.git` 全部只读；未顺手修代码。
- 唯一写入：本报告。对抗脚本仅写系统临时目录（Windows `%TEMP%` / Linux `/tmp`）。
- 方法：成功标准 → 代码合同核对 → 两平台聚焦 pytest/ruff/mypy → 未公开对抗探针（独立证券/日期，非复述实现夹具）。

## 1. 成功标准 → 独立证据 → 结论

| # | 成功标准 | 独立证据 | 结论 |
|---|---|---|---|
| 1 | 稳定脱敏 typed coverage error；区分 `missing_symbol` / `no_baseline_on_or_before_first_bar` | `adjustments.py`：`AdjustmentFactorCoverageIssue`/`Error`；单元测试区分两 reason；对抗脚本确认错误文案无路径/凭据/DataFrame 倾倒，issues 按 symbol 规范排序 | 通过 |
| 2 | 全局 preflight；任一证券失败不返回部分结果；不回退 bar 原 `adj_factor` | `_assert_first_day_baseline_coverage` 在 as-of 匹配前执行；无 `coalesce`/`fill_null`；双证券混合失败仅失败证券进 issues | 通过 |
| 3 | `effective_date <= min(trade_date)` 合法；晚一日失败；变化日用新因子 | 单元 HK 手算 `(close_t*f_t)/(close_{t-1}*f_{t-1})-1=0.34`；未来基线反例；恰首日通过 | 通过 |
| 4 | coverage 失败可保留两类 raw，不得写 factor/bar clean；显式无因子路径不变 | 集成 CountingStore 写次数均为 0；raw `bar_1d`+`adjust_factor` 保留；无因子路径 `adj_factor==1` | 通过 |
| 5 | HK 多日手算调整收益反例 | `test_first_factor_on_first_bar_day_passes_and_change_day_return_is_hand_calculated` | 通过 |
| 6 | 仍经 `Bar1dSchema`/`AdjustmentFactorSchema`；未改 Schema/依赖 | 只读核对 `schemas.py` 未在白名单；`apply` 入口仍 validate 两 Schema | 通过 |
| 7 | Windows + WSL base 聚焦测试/ruff/mypy | 见 §2；两平台均退出码 0 | 通过 |

## 2. 两平台聚焦验证（初验自跑，非复述交付报告）

### Windows（`D:\Miniforge3\python.exe`）

| 命令 | 结果 |
|---|---|
| `pytest tests/unit/test_adjustments.py tests/integration/test_bar_pipeline.py -q -p no:cacheprovider` | 16 passed；exit 0 |
| `ruff check` 白名单四 Python 文件 | All checks passed；exit 0 |
| `mypy src/quant/data/adjustments.py src/quant/data/pipeline.py` | Success；exit 0 |

### Linux（WSL `/home/mabw/AI_Coding_win/QuantitativeTrading`，`conda run -n base`）

| 命令 | 结果 |
|---|---|
| 同上 pytest | 16 passed；exit 0 |
| 同上 ruff | All checks passed；exit 0 |
| 同上 mypy | Success；exit 0 |

（pandera/polars DeprecationWarning 与本包合同无关，未计失败。）

## 3. 未公开对抗探针（实现者夹具未使用的证券/日期）

脚本：系统临时目录 `m1_x1_adversarial_iv.py`（Windows Temp + `/tmp`）；证券 `600000.SH`（合法首日基线）+ `09988.HK`（首因子晚一日）；日期 `2026-05-12/13`。

| 探针 | 期望 | Win | Linux |
|---|---|---|---|
| 合法+未来基线 → 两 Counting clean `upsert_calls==0`，无 clean parquet | fail-closed 零 clean 写 | PASS | PASS |
| 两类 raw（`bar_1d`/`adjust_factor`）仍保留 | coverage 失败不删 raw | PASS | PASS |
| bars/factors 重排后成功结果与错误 symbol 集合不变 | 行序无关；issues=`[09988.HK]` | PASS | PASS |
| 显式无 factor_mapper/store：同 bars 成功且 `adj_factor=={1.0}` | 新门禁不误伤 | PASS | PASS |
| 错误码/符号集合脱敏：reason=`no_baseline_on_or_before_first_bar`；文案无盘符/`/home`/`token`/`DataFrame`；合法证券不进 issues | 脱敏 + 规范集合 | PASS | PASS |

两平台均打印 `ALL_ADVERSARIAL_PASS`，exit 0。

## 4. 代码合同抽查（只读）

- `pipeline.update`：factor 路径先 `apply_adjustment_factors`（内含 preflight），通过后才 `factor_store.upsert`；coverage 异常发生在两 clean 写入之前。
- 未启用 `factor_mapper`/`factor_store` 时不进入复权分支，行为与改造前显式不复权一致。
- 空 bars 短路返回，不要求因子（与任务书空输入语义一致）。
- 白名单外包根导出未改；typed error 由 `quant.data.adjustments` 直接引用，符合“不越权改包根”。

## 5. 返工项

无。

## 6. 残余风险（非本包返工，供主验注意）

- 覆盖门禁对象为**已返回 bar 的证券**；请求列表中无 bar 返回者不进入本门禁（交付报告已披露，与任务书口径一致）。
- coverage 通过后、质量门禁失败前会先写 factor clean（既有编排顺序）；本任务书只约束 coverage 失败路径。主验若关心质量失败与 factor clean 原子性，需另开契约。
- 本包为零网络合同加固；不证明真实 `hk_adjfactor` 权限或连续运行。

## 7. 明确非宣称

独立初验通过 ≠ 主验通过 ≠ M1 Gate 关闭 ≠ 真实港股复权权限验收。
