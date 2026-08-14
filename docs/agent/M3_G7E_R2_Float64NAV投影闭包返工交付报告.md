# M3 G7E R2：Float64 NAV 投影闭包返工交付报告

日期：2026-08-10
状态：**实现者返工与双平台自测完成，待未参与 R2 的全新独立上下文复验**

## 1. 交付结论

R2 已按任务单 §14 最小修复正式单场景账户回放的 Float64 NAV 投影闭包。Decimal 账户经济恒等式仍在
投影前严格验证；输出时先分别投影 `cash`、`market_value`、`cash_receivable` 与
`stock_receivable_value`，再严格按现有 Schema 的同一左结合顺序生成 Float64 `equity`。
`unit_nav`、`daily_return`、下一 session 的 `previous_equity` 与其余账户状态继续使用原 Decimal
`equity`，未修改或绕过 Schema。

本报告只声明实现者返工和自测完成，不声明独立复验、主验、G7E、G7F、M3 或 Gate PASS。

## 2. 返工闭环

### 2.1 现象

R1 把四个 NAV 经济分量和 Decimal `equity` 分别独立转换为 Float64。即使投影前 Decimal 恒等式成立，
二进制浮点舍入也可能令独立 `float(equity)` 不等于现有 Schema 按四个 Float64 分量左结合求出的精确和，
使合法的 public 回放在最终 NAV Schema 校验处失败。

### 2.2 根因与应遵循规则

根因是输出 `equity` 没有以 Schema 的 Float64 计算顺序为唯一投影口径。修复后分层不变量为：

1. Decimal 层先验证 `equity == cash + market_value + cash_receivable + stock_receivable_value`；
2. 四个经济分量各自投影为 Float64；
3. 输出 `equity` 只由这四个 Float64 分量按 Schema 同序左结合生成；
4. 收益率和后续 session 仍使用 Decimal `equity`，Float64 只作为七表展示投影。

### 2.3 最小复现与新增测试

- 数值控制使用 Decimal `0.1 + 0.2 == 0.3`：独立 `float(0.3)` 与
  `float(0.1) + float(0.2) + float(0) + float(0)` 不相等；测试断言 NAV 输出 `equity` 精确等于后者，
  同时断言 `unit_nav` 仍来自原 Decimal `equity`。
- public ex-date 首次买入场景让事件证券在 record date 为零目标、ex-date 首次出现正目标；测试断言实际
  `BUY` 存在、没有追溯 entitlement 或 `CAPTURE`，并由 public API 成功返回全部七张经现有 Schema 验证的表。
- 原 R1 六项继续覆盖 fresh verifier exact-once/hostile/nonexact/stale、caller hostile Decimal context、
  独立 mark book、FULL_DAY、record/ex 时序、CAPTURED 不进 NAV、gross/2、row shuffle 与五日 golden。

通过条件是上述新旧回归、正式邻接、双平台静态检查、冷导入与白名单 diff-check 全部通过；返工后仍必须
进入未参与 R2 的全新独立复验。

## 3. 文件范围

- `src/quant/backtest/a_share_simulator.py`：最小调整 NAV Float64 输出投影；
- `tests/unit/test_m3_g7e_formal_a_share_simulator.py`：新增 R2 数值反例与 public ex-date 首次买入回归；
- `docs/agent/M3_G7E_R1正式A股单场景账户回放任务单.md`：更新为待全新独立复验；
- 本报告。

R2 未修改 `src/quant/backtest/__init__.py`，也未修改 F0、G7C、F1、F2、Schema、配置、正式 artifact 或
其他 G7E 之外生产语义。

## 4. 验证证据

Windows Miniforge，工作树自身 `src`：

- G7E unit + golden：`8 passed`；
- F0/G7B/G7C/F1/F2 + development simulator 邻接：`90 passed`；
- 定向 Ruff：通过；
- mypy `a_share_simulator.py`：通过；
- cold import：通过。

WSL Miniforge `base`，同一工作树：

- G7E unit/golden 与上述邻接合并：`98 passed`；
- 定向 Ruff：通过；
- mypy `a_share_simulator.py`：通过；
- cold import：通过。

测试仅有 Pandera 已知 deprecation warnings，无失败。WSL 工作树是 Windows 文件系统映射，因此以上仅作
双平台兼容证据，不声明 Linux/ext4 Gate。

## 5. 剩余风险与下一步

- 七表仍是普通内存值，不是 authority；G7F 继续禁止实现，且不得把本轮自测当作 G7E 或 Gate 关闭证据；
- §13 模块化 fixture 仍由已主验的 F0 套件承担来源闭包，本轮没有重新运行完整 G1；
- shared worktree 含其他里程碑既有改动，本轮仅对任务白名单负责；
- 下一步必须由未参与 R2 的全新外部 Agent 独立复验，再由主 Agent 决定是否进入最终验收。
