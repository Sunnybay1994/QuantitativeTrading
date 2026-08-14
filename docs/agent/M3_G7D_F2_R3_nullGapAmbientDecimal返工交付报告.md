# M3 G7D-F2 R3 null-gap ambient Decimal 返工交付报告

日期：2026-08-10  
角色：外部实现 Agent  
状态：**实现与双平台自测完成；待全新独立复验。G7E 继续暂停。**

## 1. 返工结论

本轮按任务书 §17 关闭了 F2 formal null-gap notional 的 ambient Decimal 逃逸。生产改动仅把构造与
transition validator 中的两次 Decimal 绝对值计算改为 `copy_abs()`；没有调整 caller context，没有依赖
G7E 固定 precision，也没有改变 F2 public API、值对象、§14～§16、费用、allocation 或 development 行为。

## 2. 现象—根因—规则—最小复现—通过条件

- 现象：同一个 FULL_DAY/null-quantity 合法输入在默认 precision 28 可完成，在 caller precision 50 时由 F2
  自己构造的 transition 被自身 `__post_init__` 拒绝。
- 根因：构造端在私有 precision 80 context 内执行 `abs(target_notional - current_value)`；validator 先用私有
  context subtract，退出私有 context 后再执行 ambient-sensitive `abs(...)`。长循环小数因此在不同位置被 caller
  precision 再舍入，`rejected_notional` exact compare 失败。
- 应遵循规则：所有 formal Decimal 中间算术必须在私有 context 或使用不依赖 ambient context 的 exact Decimal
  primitive；本处使用私有 subtract 结果的 `copy_abs()`。
- 最小复现：FULL_DAY 的 `000001.SZ` 持仓 100 股，mark 为 80 位循环小数，目标权重 0，分别在 caller
  default 28、precision 50、precision 4 + `ROUND_DOWN` + `Inexact` trap 下执行 public F2。
- 新增测试：三种 caller context 均完成 build 和 transition `__post_init__`；逐 dataclass field exact 相同；
  precision、rounding、Emax、Emin、traps、flags 调用前后相同；只漂移 null-gap `rejected_notional` 仍拒绝。
- 通过条件：§17 新反例、既有 ordinary rejection、§14 special、reference digest/whole-rehash 以及双平台邻接
  全部绿色。

## 3. 文件与定向审查

本轮修改：

- `src/quant/backtest/a_share_execution.py`：两处 null-gap Decimal absolute 改为 `copy_abs()`；
- `tests/unit/test_m3_formal_a_share_session_execution.py`：新增 ambient-independent 逐字段回归；
- `docs/agent/M3_G7D_F2_R1正式A股Session订单执行状态转移任务单.md`：只更新 R3 状态；
- 本报告。

对 `a_share_execution.py` 全文件定向检索 `abs(`：除本轮两处 formal Decimal null-gap 外，只存在一处
development 整数 quantity absolute，按 §17 明确不改。未发现其他同类 formal Decimal unary absolute 逃逸。

## 4. 验证证据

Windows Miniforge，工作树自身 `src`：

- 新增 R3 单测：`1 passed`；
- F2 formal + F1 + development execution/allocation：`112 passed`；
- F0 + G7C + development simulator：`37 passed`；
- Ruff：通过；
- mypy `a_share_execution.py`：通过；
- cold import/API boundary：通过；
- `git diff --check`：通过。

WSL Miniforge `base`，同一工作树：

- F2 formal + F1 + development execution/allocation：`112 passed`；
- F0 + G7C + development simulator：`37 passed`；
- Ruff：通过；
- mypy `a_share_execution.py`：通过；
- cold import/API boundary：通过。

测试只有 Pandera deprecation 与受限 `.pytest_cache` 写入 warning，无失败。WSL 工作树位于 DrvFS 映射，以上
只作为双平台兼容证据，不声明 Linux/ext4、F2 主验、G7、M3 或 Gate PASS。

## 5. 边界与剩余风险

- 未修改 G7E simulator/tests；G7E 按 §17 继续暂停。
- 未修改 F0/F1/G7C、Schema、config、`__init__.py` 或正式 artifact；未联网、未访问真实数据/账户、未
  add/commit/push。
- shared worktree 存在其他里程碑的既有改动；本轮只对上列四个白名单文件负责。
- 当前结果是实现者自测，不替代全新外部 Agent 的独立复验或主 Agent 最终验收。
