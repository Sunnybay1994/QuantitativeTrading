# M3 G7D-F2 R3 null-gap ambient Decimal 独立复验报告

日期：2026-08-10  
角色：未参与 R3 实现的独立初验 Agent  
结论：**PASS；仅解锁主 Agent 最终验收。G7E 在主验 PASS 前继续暂停。**

## 1. 范围与职责分离

本轮完整读取并逐项映射：

- `M3_G7D_F2_R1正式A股Session订单执行状态转移任务单.md` §17；
- `M3_G7D_F2_R3_nullGapAmbientDecimal返工交付报告.md`；
- `M3_G7D_F2_R2_referenceOpen与RejectionNotional闭包主Agent最终验收报告.md`；
- 当前最终 `src/quant/backtest/a_share_execution.py` 与
  `tests/unit/test_m3_formal_a_share_session_execution.py`。

生产代码和实现者测试保持只读；本报告是本 Agent 唯一写入。未联网、未访问真实数据或账户、未执行
`git add/commit/push`。共享工作树存在其他里程碑既有改动，本报告不把全树脏状态归因于 R3。

## 2. 契约与代码核对

§17 的缺口是 null/open-unknown gap 在私有 80 位 subtraction 后又调用 ambient-sensitive `abs(...)`，造成构造端
与 validator 在 hostile caller context 中可能得到不同精度的金额。当前最终实现把两处都收敛为私有运算结果的
`copy_abs()`：

1. `_formal_build_intents` 构造 null-gap `rejected_notional` 使用
   `(target_notional - current_value).copy_abs()`，该表达式位于私有 formal math context 内；
2. `_validate_formal_session_transition` 使用
   `_formal_subtract(intent.target_notional, current_value).copy_abs()` 重算并 exact compare；
3. F2 public API、transition 字段、§14 target-attainability、§15 ordinary rejection notional、§16
   `reference_opens_sha256`、费用和 allocation 语义均未因本修复改变；
4. 对 `a_share_execution.py` 定向检索全部 `abs(` 后，formal F2 Decimal 路径未发现其他同类 unary absolute
   逃逸；剩余 `abs(target_quantity - current_quantity)` 属于 development 整数 quantity，符合 §17 的明确排除项。

## 3. 独立新增对抗

实现者覆盖 default 28、prec 50、prec 4 + `ROUND_DOWN` + Inexact trap。本轮另用同一个可达 FULL_DAY 持仓
null-gap case，在 Windows 与 WSL base 分别新增以下 caller context 组合：

| precision | rounding | Overflow trap | Inexact trap |
|---:|---|---:|---:|
| 17 | `ROUND_CEILING` | on | off |
| 50 | `ROUND_FLOOR` | off | on |
| 79 | `ROUND_HALF_EVEN` | on | on |

每组都执行 public F2 build，再通过 `dataclasses.replace(transition)` 触发完整 `__post_init__` 重构校验。结果：

- 三组 transition 的 16 个 dataclass 字段逐字段相等；
- 每次 build 与重构前后 caller precision、rounding、Emax、Emin、traps、flags 完全不变；
- 对合法 transition 只漂移 null-gap `rejected_notional` `+0.0000001`，重构稳定拒绝；
- Windows 输出 `R3_ADVERSARIAL_WINDOWS_PASS 3 16`；
- WSL 输出 `R3_ADVERSARIAL_WSL_PASS 3 16`。

独立对抗没有复用实现者的 prec 4/ROUND_DOWN 组，且同时覆盖中等、较高精度和不同 trap 组合。

## 4. 当前最终 revision 回归

所有命令均从 `artifacts/dev_worktrees/m3-g4-formal` 使用该工作树自身 `src`。

### 4.1 Windows 原生 Miniforge

- F2 formal + F1 + development execution/allocation：**112 passed**，230.13s；
- F0 + G7C + development simulator：**37 passed**，219.66s；
- Ruff（production + formal F2 test）：**PASS**；
- mypy `--no-incremental --show-traceback`：**PASS**，1 source file；
- cold import/public signature：**PASS**；signature 无 `open_states`，未加载 qlib/lightgbm/mlflow；
- R3 白名单 `git diff --check`：**PASS**，仅有既有 LF/CRLF 提示，无 whitespace error。

### 4.2 WSL Miniforge base

- F2 formal + F1 + development execution/allocation：**112 passed**，208.13s；
- F0 + G7C + development simulator：**37 passed**，184.99s；
- Ruff：**PASS**；
- mypy `--no-incremental --show-traceback`：**PASS**，1 source file；
- cold import/public signature：**PASS**；signature 无 `open_states`，未加载 qlib/lightgbm/mlflow。

pytest 只有 Pandera deprecation 与受限 `.pytest_cache` 写入 warning，无产品失败。WSL 默认把 mypy SQLite cache
放到 DrvFS 时首次出现 `sqlite3.OperationalError: disk I/O error`；改用 WSL `/tmp` 后同一最终源码 PASS。
Windows 一次把 cache 指向 `NUL` 也因 mypy 2.3.0 尝试创建 `NUL\\3.13` 而失败；改用系统临时目录后 PASS。
这两次是缓存路径错误，不计作通过证据，也没有重复运行长 pytest 组。

当前 SHA256：

- `a_share_execution.py`：`32F4D26AFCC34FE318BE578FF33E106AE702F4AE77F6BD6B86D62931AD21334B`；
- `test_m3_formal_a_share_session_execution.py`：`9525B0F1A33AEB0534A8CA2D71BF8E6ACEE838050DA90C863A399E092381702A`；
- F2 任务单：`2069471721B06CE21429255035B551EE9F3F1C0F48E0A73DAD63A23983709A0C`；
- R3 交付报告：`A3DC5EDFA5E58B090F722CD668D383AE51C36E3C395D888D1436918ABC6AD98F`。

## 5. 上游独立问题与边界

定向审查同时确认 F1 open projection 的
`upper - _PRICE_TICK / 2`、`lower + _PRICE_TICK / 2` 仍在 caller ambient Decimal context 中执行。该 F1 open
division 缺口属于独立上游问题，不是本轮 F2 §17 null-gap 修复白名单，也没有被归为 F2 R3 FAIL；后续应由主
Agent 单独冻结 F1 返工与对抗验收，不能在 F2 主验中静默扩范围修改。

当前 WSL 实路径位于 `/mnt/f` 的 DrvFS，不是 Linux ext4。本 PASS 不代表 G7E、G7、M3、真实数据/成本、完整
账户回测或任何发布 Gate PASS；只允许进入主 Agent 对 G7D-F2 R3 的最终验收。
