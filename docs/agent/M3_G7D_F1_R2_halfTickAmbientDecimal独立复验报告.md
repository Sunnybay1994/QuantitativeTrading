# M3 G7D-F1 R2 half-tick ambient Decimal 独立复验报告

日期：2026-08-10  
角色：未参与实现的全新独立初验 Agent  
结论：**PASS；仅允许进入主 Agent 最终验收。G7E 继续暂停，不等于 F1 R2、完整 G7D、Linux/ext4 或 M3 Gate PASS。**

## 1. 独立复验范围

完整核对 F1 任务书 §12、R2 返工交付报告、R1 主 Agent 最终验收报告与当前生产实现。生产代码和实现者
测试全程只读；本报告是唯一写入文件。未联网、未访问真实数据或账户、未 add/commit/push。

本轮只判断 formal F1 的 half-tick 边界是否摆脱 caller ambient Decimal context；不重新解释 development
语义，不扩大到 F2、G7C、G7E、账户回测或发布 Gate。

## 2. 合同与代码核对

- formal half tick 是 exact `Decimal("0.005")`，没有 ambient 除法；
- upper 阈值只由既有私有 80 位 `_formal_subtract` 产生，lower 阈值只由 `_formal_add` 产生；两个 helper
  使用私有 local context 并在 `finally` 退出，不修改 caller context；
- formal 比较仍为 `open < upper - half_tick` 与 `open > lower + half_tick`，所以精确等号继续拒绝；
- `Decimal(str(float))`、FULL_DAY/PARTIAL、板块、数量规则和两个 public API 均未因 R2 改义；
- 全文件扫描仅在 development `build_open_execution_states` 路径保留 `_PRICE_TICK / 2`。formal F1 路径没有
  ambient half-tick division/add/sub 残留，符合冻结边界。

## 3. 独立对抗性反例

### 3.1 hostile Decimal context

选择同一合法 formal F0 capability 和同一开盘事实，先在 default context 建立基线，再覆盖：

- precision：3、17、50、79；
- rounding：`ROUND_CEILING`、`ROUND_FLOOR`、`ROUND_HALF_EVEN`；
- `Inexact` 与 `Overflow` trap 同时启用；
- 调用前清空 flags，并记录 precision、rounding、Emax、Emin、capitals、clamp、全部 traps 与 flags。

12 个 hostile context 中，`build_formal_a_share_open_execution_states` 的 Schema 和逐字段值均与 default
基线完全一致；`resolve_formal_a_share_order_quantity_rule` 的所有 dataclass 字段也完全一致。两个 API 返回后
caller context、traps 和 flags 逐项不变。共执行 24 次 hostile public API 调用，全部通过。

### 3.2 精确等号与微小边界

以 open `10.0` 验证六组独立边界：upper/lower 精确半 tick 等号、向拒绝区内侧偏移、向允许区外侧偏移。
由于权威 Schema 存储为 Float64，最初 `1e-15` 差值在入表时与 `10.005` 归并，不能构成有效反例；随后改用
仍很小但可穿过 Float64 存储的 `1e-12` 差值。最终六组方向、含等号语义全部符合任务书。

### 3.3 capability 身份先验

分别构造 fake、development capability 与 formal subclass，并令其 property/attribute 访问立即记录并抛错。
两个 public API 对三类输入共六次调用均稳定返回 `M3_A_SHARE_EXECUTION_INVALID`，`cause/context` 为空，访问
记录保持空列表，证明 exact type 检查仍先于任何 capability property 访问。

## 4. 当前合流回归证据

Windows Miniforge，工作树自身 `PYTHONPATH=src`：

- F0/F1/F2 formal + development facts/execution：`120 passed` + `15 passed`，合计 `135 passed`；
- G7C formal corporate actions + development simulator：`14 passed`；
- Ruff：PASS；mypy `--no-incremental --show-traceback`：PASS；cold import：PASS；
- scoped `git diff --check`：退出 0，仅有既有 LF/CRLF 提示。

WSL Miniforge `base`，同一 `/mnt/f` 工作树：

- F0/F1/F2 formal + development facts/execution：`135 passed`；
- G7C formal corporate actions + development simulator：`14 passed`；
- Ruff：PASS；mypy `--no-incremental --show-traceback`：PASS；cold import：PASS。

测试只有 Pandera deprecation 与受限 `.pytest_cache` warning。Windows 首次把 135 与 14 串在同一 240 秒
外层命令时被工具时限截断，pytest 未报告用例失败；随后分组以充分时限取得上述明确结果，不把超时尝试记作
PASS。首次并行静态命令的 WSL 外层引号解析失败、未执行检查；修正引号后重新执行并明确 PASS。

## 5. 结论与剩余边界

R2 已关闭 formal F1 half-tick 算术对 caller precision、rounding、traps 与 flags 的依赖，并保持 exact 等号、
微小边界和 capability 身份不变量。独立初验结论为 PASS，可进入主 Agent 最终验收。

工作树位于 `/mnt/f` DrvFS，不是 ext4；本报告不声明 Linux/ext4、G7E、完整 G7D、G7、M3 或任何正式 Gate
通过。F1 R2 在主验明确 PASS 前，G7E 必须继续暂停。
