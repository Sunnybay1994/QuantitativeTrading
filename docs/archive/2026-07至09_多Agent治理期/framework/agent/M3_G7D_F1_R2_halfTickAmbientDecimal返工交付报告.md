# M3 G7D-F1 R2 half-tick ambient Decimal 返工交付报告

日期：2026-08-10  
角色：外部实现 Agent  
状态：**实现与双平台自测完成；待全新独立复验。G7E 继续暂停。**

## 1. 返工结论

本轮按 F1 任务书 §12 关闭 formal open-state 半 tick 阈值的 ambient Decimal 逃逸。生产改动仅新增 exact
`Decimal("0.005")` formal 常量，并用已有私有 80 位 `_formal_subtract` / `_formal_add` 计算 upper/lower 阈值。
没有调整 caller context，没有要求 G7E 包裹 precision 80，也没有改变 development、F0、F2、G7C、板块、停牌、
数量规则或 public API。

## 2. 现象—根因—规则—最小复现—通过条件

- 现象：合法有 open 证券在 caller precision 4、`ROUND_DOWN` 且启用 `Inexact` trap 时，F1 formal projection
  在半 tick 比较前抛 Decimal 异常。
- 根因：formal 路径直接执行 ambient `_PRICE_TICK / 2`，再用 ambient `upper - half` / `lower + half`；调用者
  precision、rounding、trap 因此进入领域判断。
- 应遵循规则：半 tick 使用 exact 常量，upper/lower 阈值必须由模块私有 Decimal context 算术生成；含等号拒绝
  与 `Decimal(str(float))` 口径不变。
- 最小复现：同一 exact F0 capability，open 10.0、upper 10.005、lower 9.9949，在 caller default 28、
  precision 50、precision 4 + `ROUND_DOWN` + `Inexact` trap 下，分别调用两个 F1 public API。
- 新增测试：三种 context 下 open-state Schema 与逐字段值相同，quantity rule dataclass 逐字段相同；caller
  precision、rounding、Emax、Emin、traps、flags 前后相同；exact upper 等号继续拒绝买入，lower 刚外继续允许卖出。
- 通过条件：新增 hostile context、既有半 tick 上下等号/刚内/刚外控制组、hostile capability 与双平台
  F0/F1/F2 邻接全部绿色。

## 3. 修改文件

- `src/quant/backtest/a_share_execution.py`：formal exact half tick 与私有 add/sub 阈值；
- `tests/unit/test_m3_formal_a_share_open_execution.py`：两个 public API 的 hostile ambient 回归；
- `docs/framework/agent/M3_G7D_F1_R1正式A股开盘执行事实任务单.md`：只更新 R2 状态；
- 本报告。

`a_share_execution.py` 的 development 半 tick 算术保持原样；本轮未借机修改非 formal 语义。

## 4. 验证证据

Windows Miniforge，工作树自身 `src`：

- 新增 hostile context + 既有六组边界控制：`7 passed`；
- F0/F1/F2 formal + development facts/execution：`135 passed`；
- G7C + development simulator：`14 passed`；
- Ruff：通过；
- mypy `a_share_execution.py`：通过；
- cold import：通过；
- `git diff --check`：通过。

WSL Miniforge `base`，同一工作树：

- F0/F1/F2 formal + development facts/execution：`135 passed`；
- G7C + development simulator：`14 passed`；
- Ruff：通过；
- mypy `a_share_execution.py`：通过；
- cold import：通过。

测试只有 Pandera deprecation 与受限 `.pytest_cache` warning，无失败。WSL 工作树位于 DrvFS 映射，以上只作为
双平台兼容证据，不声明 Linux/ext4、F1 主验、G7D、G7、M3 或 Gate PASS。

## 5. 边界与剩余风险

- F2 R3 已由主 Agent 验收通过；本轮没有修改其 frozen 语义。
- G7E simulator/tests 保持冻结，需待 F1 R2 全新独立复验与主验后再恢复。
- 未修改 F0/F2/G7C、Schema、config、`__init__.py` 或正式 artifact；未联网、未访问真实数据/账户、未
  add/commit/push。
- shared worktree 存在其他里程碑既有改动；本轮只对上列四个白名单文件负责。
- 当前结果是实现者自测，不替代全新外部 Agent 独立复验或主 Agent 最终验收。
