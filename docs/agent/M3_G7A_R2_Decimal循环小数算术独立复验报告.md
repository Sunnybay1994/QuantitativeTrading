# M3 G7A R2：Decimal 循环小数算术独立复验报告

日期：2026-08-09  
角色：未参与 R2 返工实现的全新独立复验 Agent  
结论：**PASS；允许进入主 Agent 最终验收，G7B 仍须等待主验通过后解锁**

## 1. 范围与边界

本轮完整阅读根 `AGENTS.md`、`.ai` 通用执行与审查规则、G7A 任务单新增的 R2 算术闭包、R1 FAIL
报告、R2 返工交付报告、`targets.py` 以及 formal/development target 测试。生产代码与实现者测试始终
只读；唯一新增文件是本报告。未联网、未 add/commit，未触碰正式 G1 artifacts、journal 或 G7B。

本结论只证明 G7A R2 Decimal 工程合同及其直接回归。WSL 验证位于 `/mnt/f`，实测文件系统为
`wslfs`，因此不是 Linux/ext4 Gate、真实 G1 全折、真实数据性能或 M3/M4 Gate 结论。

## 2. 返工核对

R2 将 formal `_build_frames_from_layers` 与 development `_build_target_frames` 原有的两份分配算术收敛为
同一私有 `_target_allocation`：

- `Decimal(str(...))` 输入后，用 `Fraction` 精确判断
  `max_weight * n_selected <= 1 - cash_buffer` 的 capped 分支；
- uncapped 分支只使用私有 `Context(prec=50, rounding=ROUND_DOWN)` 的副本计算 weight 与 total；
- 保留精确 `total <= investable` 断言，没有 epsilon/tolerance，也没有删除 fail-closed 检查；
- helper 不读取调用方全局 Decimal precision/rounding；formal 与 development 只调用同一 helper。

这正面关闭了 R1 将非终止除法的向上舍入尾差当作真实超配的根因，改动没有引入新的公共接口或平行格式。

## 3. 独立对抗证据

### 3.1 多选择数、封顶边界与 hostile Decimal context

Windows 和 WSL base 均运行同一不落盘探针，覆盖：

- `n_selected = 3/7/11/299`，其中 3 为 capped 控制组，7/11/299 为非终止 uncapped 除法；
- exact boundary：`cash_buffer=.1, max_weight=.3, n=3` 精确封顶；
- just-uncapped：`max_weight=.30000000000000004, n=3` 回落到精确 investable 分配；
- 全局 `Context` 为 `prec=1` 且分别使用 `ROUND_UP/ROUND_DOWN/ROUND_FLOOR/ROUND_CEILING`，另加
  `prec=2 ROUND_UP` 与 `prec=9 ROUND_CEILING`。

所有 hostile context 的 `(weight, total)` 与基线逐字相等。每组同时以 `Fraction(weight) * n <=
Fraction(investable)` 和 `total <= investable` 检查，不使用 epsilon。代表性结果：

- `0.9 / 7`：total =
  `0.89999999999999999999999999999999999999999999999994`；
- `0.9 / 11`：total =
  `0.89999999999999999999999999999999999999999999999999`；
- `0.9 / 299`：total =
  `0.89999999999999999999999999999999999999999999999997`。

formal R2 节点在 hostile context 中完成 build→receipt→verify，并把 daily total 与该 helper 结果比较；
development R2 节点以调用计数证明逐日复用同一 helper。两条路径的算术来源和结果一致。

### 3.2 R1 299-domain 最小复现

另行构造单日 299 个 eligible、298 个 scorable/predicted、连续 rank、`top_k=7`、
`cash_buffer=.1`、`max_weight=.2`，并在调用方 `Context(prec=1, ROUND_UP)` 下执行 formal frame core。
Windows 与 WSL base 均得到：

- 完整 299 行 target domain；
- 7 个正权重、292 个显式零；
- daily total 投影为 `0.9`，并满足 `<= Decimal("0.9")`；
- 不再出现 R1 的 `formal target decimal allocation exceeds investable`。

因此 R1 报告中的 299-domain 最小复现已关闭。

### 3.3 freshness、receipt、异常与不可变发布回归

双平台精确定向节点还覆盖：

- hostile prediction verifier 的固定脱敏错误、空 cause/context 与零输出；
- 三个 writer 失败位置的精确回滚；
- copied receipt/path identity 与未知 receipt input 拒绝；
- 首字节前 output-root 实体替换拒绝；
- foreign whole-bundle 替换拒绝；
- formal R2 build/verify 与 development 共享 helper 回归。

上述六节点两平台均通过，未发现 receipt、freshness、异常脱敏或发布不变量退化。

## 4. 验证命令与实际结果

Windows 原生 Miniforge（显式把当前 worktree `src` 置于导入首位）：

- 六个关键 pytest 节点：`6 passed`，174.85 秒；仅 Pandera deprecation warnings；
- Ruff（`targets.py` 与两份 target 测试）：`All checks passed!`；
- mypy（`targets.py`）：`Success: no issues found in 1 source file`；
- 私有 helper hostile-context 探针：`R2_PRIVATE_HELPER_HOSTILE_CONTEXT_PASS`；
- 299-domain 探针：`R1_299_DOMAIN_MINIMAL_REPRO_CLOSED 299 0.9`。

WSL Miniforge `base`：

- 同组六个 pytest 节点：`6 passed`，79.57 秒；仅 Pandera deprecation warnings；
- Ruff：`All checks passed!`；
- mypy：`Success: no issues found in 1 source file`；
- 私有 helper hostile-context 探针：`R2_WSL_PRIVATE_HELPER_HOSTILE_CONTEXT_PASS`；
- 299-domain 探针：`R1_299_DOMAIN_WSL_MINIMAL_REPRO_CLOSED 299 0.9`；
- `stat -f -c %T ...`：`wslfs`。

有两项命令环境事实未计为绿测：第一次 Windows pytest 因当前 worktree `src` 未优先，收集时加载了别处的
`quant` 并报 `ModuleNotFoundError`；修正导入优先级后解决。随后一次 formal+development 全组等待在
360 秒处由承载层超时，原 pytest 子进程仍存活并最终自然退出，但最终摘要不可回收，故未把该次记为通过；
只在确认原进程结束后才运行上述可回收的六节点集合。

## 5. 最终判定

R2 以最小共享 helper 正确关闭了 R1 的循环小数尾差误拒问题。独立新增的 n=3/7/11/299、exact/just-
uncapped、极端全局 Decimal context 和双平台 299-domain 反例均通过；formal/development 算术一致，精确
`total <= investable` 不变量成立，直接 freshness/receipt/异常/发布回归未退化。

本轮独立复验结论为 **PASS**。G7A 可进入主 Agent 最终验收；只有主验通过后才可解锁 G7B。Linux/ext4
Gate 与真实数据结论继续保持未关闭。
