# M3 G7F R1：正式 A 股三场景回测 Artifact 独立初验报告

日期：2026-08-10  
状态：**FAIL；不得解锁主 Agent 最终验收**

## 1. 结论

G7F 两个新增测试文件在 Windows 与 WSL/DrvFS 均通过，独立补充的 Decimal、整包合法重签、hostile 异常图和
tree identity 对抗也全部通过；formal production 主路径未发现接受 caller result、跳过 fresh verifier/F0、复用 1×
结果或绕过 29-file transaction/21-input receipt 的入口。

但是，任务单 §13 要求的 G7B/F0/G7C/F1/F2/G7E/P0 同进程邻接回归不通过：153 项中 148 passed、5 failed。
最小两节点顺序可稳定复现 `corporate_actions` reload 后 actual G7E formal replay 自拒绝。因此本轮独立初验必须
判定 FAIL；通过的局部证据不能覆盖强制邻接失败，也不能声明 G7F、完整 G7、Linux/ext4 或 M3 Gate PASS。

本轮只新增本报告。生产代码、实现测试、任务书、既有报告与正式 artifact 均保持只读；未联网、未访问真实数据、
账户或券商，未执行 add/commit/push。

## 2. 审查对象与冻结哈希

- `src/quant/backtest/a_share_reporting.py`：
  `698937E25AE69505497565FE65722E4E694AE2B7B00E50ECF0370332085B3A81`
- `src/quant/backtest/__init__.py`：
  `6D68F1488646C2432FE78684450871136FA824492A99F63C4B56499A65EA3D84`
- `tests/unit/test_m3_g7f_formal_backtest_artifact.py`：
  `B3A28FEC24D63F02E259FD1A11E9779B04976976C0EF9986718A0E9B81866A3E`
- `tests/integration/test_m3_g7f_formal_backtest_artifact_golden.py`：
  `3B13FE167E8586E014EC530C578E2E853D9D513E1EA36CAACAF1B639E2F150CE`
- G7F 任务单：
  `BD82C85A988F6D3778CF16A325B61668E1A112EDFCF5DD76A4FFA6B1D7D759AF`
- G7F 交付报告：
  `A8D1A27BDA9E2266DE803453626F65673704C0BC69ECF100F9CCC0DE309B77C5`

同时定向阅读了 G7E、P0、G7B/F0/G7C/F1/F2 public 合同、receipt verifier、nested
`ArtifactPublication` 与相关测试。模块化 fixture 只按任务单 §15 使用；它不重新证明 full G1 retained release 来源，
本报告不把它表述为真实 formal release。

## 3. 合同映射与已通过证据

### 3.1 Fresh 链与三次 actual G7E

- production `_formal_bundle` 先执行 exact outer/nested/path 校验，再调用 G7F import 的 public plan verifier 一次、
  public F0 loader 一次；只使用 fresh plan 的 scheduled targets。
- actual `simulate_formal_a_share_scenario` 固定按 `0.5, 1, 2` 调用三次，每次显式传相同 facts、base periods、
  initial cash 与 fresh context；public surface 没有 caller result/fills/transition/schedule/metrics 入口。
- Windows/WSL G7F 正向测试实际观察到 builder 与 verifier 各自的 `plan -> facts -> G7E x3` 顺序。三场景
  multiplier、common facts identity、独立 result 与 scenario 顺序均受 exact 检查约束。

### 3.2 指标、benchmark 与 terminal disclosure

- formal 指标只在 80 位、`ROUND_HALF_UP` 私有 Decimal context 内计算，最终投影 finite float；annualized、
  prepend-1 drawdown、net excess、relative wealth、fees、cash ratio 与累计 NAV 对账均由源码和 golden 覆盖。
- benchmark 只接受 `510300.SH`，按 execution dates 精确覆盖，使用首日 raw open 与末日 raw close。
- target turnover 从全现金零权重开始；realized one-way 强制等于 gross/2。rejection count 按有 residual 的唯一
  `(date,symbol,side)` 去重，不按 reason rows 计数。
- terminal exit 使用 base 1× period、SELL floor-to-0.01 tick、actual execution notional、逐分项 HALF_UP fee、
  odd-lot 全余额与 minimum commission；不扣 NAV，不使用 scenario multiplier，也不以 mark-notional 粗估。

独立 hostile Decimal public-builder probe 覆盖 default 28、prec 3/17/50/79，rounding 为 CEILING/FLOOR/DOWN/
HALF_EVEN，启用 Inexact/Overflow traps 并预置 caller flag。五次均成功生成 exact 三场景 artifact，caller precision、
rounding、traps 与 flags 逐字段不变；actual G7E/G7C/F1/F2 未 mock。

### 3.3 29 outputs、strict bytes、whole-rehash 与 receipt

- builder 通过一个 nested `ArtifactPublication` lease 覆盖 fresh、三回放、序列化、owned-handle readback 与一次
  `commit(29 exact paths)`；七表（包括空表）、scenario metrics/manifest 与 root metrics/manifest 集合精确。
- scenario manifest 精确 8 个 self-excluding entries；root scenario 顺序为 `0p5x,1p0x,2p0x`；JSON canonical，
  Parquet 参数、Schema、列顺序、dtype、行顺序和值均重建比较。
- verifier 先 snapshot root/children/29 files，再 fresh 重放三次、逐文件 bytes equality，最后复验 receipt 的
  21 inputs/29 outputs 并重查 whole-tree identity。

独立整包攻击执行了以下步骤：重排三个 scenario 的全部非空 Parquet；修改 `1p0x` metrics；同步重算三个
scenario manifests、root metrics、root manifest 及所有受影响 hash；发布一张新的、内部自洽的 receipt。共享
receipt verifier 先确认该恶意 receipt 的 21 inputs/29 outputs 全部有效，G7F verifier 随后仍因 fresh actual 三回放
稳定拒绝，错误仅为 `M3_A_SHARE_BACKTEST_ARTIFACT_INVALID`，cause/context 均为 `None`。该 probe PASS。

### 3.4 Hostile tree、事务与错误脱敏

- 独立 tree probe 覆盖 extra、missing、两 expected leaf 互为 hard-link alias，以及 leaf/child/root/ancestor
  同名替换；均在 exact tree 或 snapshot identity 比较中拒绝。
- 递归 hostile exception probe 构造 cause/context 互相成环且 `str/repr` 含 TOKEN、SQL、私有路径与 PID 的异常。
  public builder 只返回稳定错误，cause/context 均为空，owned output 精确回滚，root 保持空。该 probe PASS。
- P0 全文件邻接覆盖 nested/flat 一次提交、case/file-directory alias、pre-existing child/leaf no-clobber、writer
  failure、post-open identity recheck、foreign entry 与 owned-only rollback。相关 P0 项在 153 项组合中的前段通过；
  G7E reload 顺序失败发生在其后。

## 4. 验证结果

### 4.1 G7F 定向

- Windows Miniforge，G7F unit + golden：`10 passed`，`468.16s`。
- WSL Miniforge base，同一 `/mnt/f` 工作树，G7F unit + golden：`10 passed`，`378.52s`。
- Windows 与 WSL：定向 Ruff 均 `All checks passed!`；mypy 均 `Success: no issues found in 1 source file`；
  cold import 均通过。
- 白名单定向 `git diff --check` 无 whitespace error；只出现 Git 的既有 LF/CRLF 提示。

WSL 工作树位于 DrvFS，以上只能作为兼容证据，不能声明 Linux/ext4 Gate。

### 4.2 强制邻接失败

同一 WSL pytest 进程运行：

```text
test_m3_backtest_plan_artifact.py
test_m3_nested_artifact_publication.py
test_m3_formal_a_share_market_facts.py
test_m3_corporate_actions.py
test_m3_formal_a_share_open_execution.py
test_m3_formal_a_share_session_execution.py
test_m3_g7e_formal_a_share_simulator.py
test_m3_g7e_formal_a_share_simulator_golden.py
```

实际结果：`148 passed, 5 failed`，`311.83s`。失败项：

1. `test_formal_replay_uses_fresh_plan_exactly_once`；
2. `test_ex_date_first_buy_has_no_retroactive_entitlement_and_float_nav_closes`；
3. `test_formal_replay_account_identities_and_row_order_stability`；
4. `test_formal_replay_isolates_hostile_decimal_context`；
5. `test_five_session_three_security_golden`。

单独运行第 1 项：`1 passed`，`32.84s`。按固定顺序运行下列两个节点：第一个 PASS，第二个 FAIL：

```text
tests/unit/test_m3_corporate_actions.py::test_corporate_action_core_import_does_not_load_qlib
tests/unit/test_m3_g7e_formal_a_share_simulator.py::test_formal_replay_uses_fresh_plan_exactly_once
```

最小复现结果：`1 passed, 1 failed`，G7E public API 稳定报
`AShareSimulationError: M3_A_SHARE_SIMULATION_INVALID`。

## 5. 必须返工项

### 5.1 现象

`test_corporate_action_core_import_does_not_load_qlib` 在 pytest 已收集并导入 G7E simulator 后，对
`quant.backtest.corporate_actions` 执行原地 `importlib.reload(...)`。该测试自身通过，但其后的 actual G7E formal
replay 全部自拒绝；单跑 G7E 又通过，证明是确定的同进程顺序污染。

### 5.2 根因

Python reload 会在现有 module object/dict 上重新执行代码并创建新的 `EntitlementReplayPhase`、opaque replay
state/transition class identity。G7E simulator 在 reload 前通过 `from ... import ...` 保留旧 enum/class identity；其已
导入的函数对象所引用的 module globals 则在 reload 后指向新 identity。于是 replay 生产者与 simulator 的 exact
identity/phase 消费者分裂为新旧两代，最终被 formal fail-closed 路径转换成稳定 simulation error。

该问题不是 G7F builder 接受伪造数据，而是强制邻接测试破坏了 G7C/G7E 的同进程身份不变量。实现者报告的
`135 passed` 未覆盖上述固定顺序，不能作为任务单 §13 的完整邻接证据。

### 5.3 应遵循规则

- import/cold-load 测试不得污染后续已收集模块的 class/enum identity；测试必须顺序独立。
- formal exact-type/opaque issuer 不变量不能为迁就测试 reload 而放宽。
- G7F 任务单 §13 的邻接回归必须在同一进程按可复现顺序通过；局部单跑绿色不能替代。
- 本问题位于 G7F 实现白名单外，独立初验者不得直接修改 G7C/G7E 或测试后跳过职责分离。

### 5.4 最小返工建议

优先把 `test_corporate_action_core_import_does_not_load_qlib` 的 cold-import/不加载 Qlib 断言移入全新子进程，避免
在主 pytest 进程 reload 被 G7E 等模块消费的 production module。不要放宽 production exact type、issuer、phase 或
fresh 校验。若选择其他方案，必须证明 reload 后所有 downstream consumer identity 一致且不隐藏真实漂移。

### 5.5 必须新增测试与通过条件

1. 增加固定顺序回归：先运行 corporate-actions cold-import 节点，再运行 actual G7E formal replay 正向、hostile
   Decimal 与 golden；Windows 与 WSL base 均须 PASS。
2. 同一进程重跑本报告的 153 项集合，必须 `153 passed`；不得通过改顺序、排除 reload 节点或拆进程掩盖污染。
3. 重新运行 G7F 两文件双平台测试、定向 Ruff/mypy/cold import，继续全部绿色。
4. 返工必须由实现 Agent 完成，再由未参与返工的全新独立初验 Agent 复验；只有复验 PASS 才可解锁主验。

## 6. 未通过边界与剩余风险

- 本轮独立初验 FAIL；G7F 状态必须保持未完成。
- 未执行全量 pytest，因为更小的强制邻接集合已给出稳定失败和两节点最小复现；在返工前重复全量没有新增价值。
- 未执行 Linux/ext4 验证；WSL 结果来自 DrvFS。
- 未重新构造 full G1 retained formal release；按任务单 §15 仅使用已裁决的模块化 fixture，来源闭包仍由各上游
  formal 套件承担。
- 已通过的 Decimal、whole-bundle、tree、receipt、P0 与脱敏对抗应保留为返工后的回归证据，但不能改变本轮
  FAIL 结论。
