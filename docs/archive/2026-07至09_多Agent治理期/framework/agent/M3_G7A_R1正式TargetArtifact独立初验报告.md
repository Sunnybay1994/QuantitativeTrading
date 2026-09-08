# M3 G7A R1：正式 TargetArtifact 独立初验报告

日期：2026-08-09  
角色：未参与实现的独立初验 Agent  
结论：**FAIL，退回最小返工；G7B 尚未解锁**

## 1. 初验范围与边界

本轮完整阅读了根 `AGENTS.md`、`.ai` 通用审查规则、G7A 任务单与交付报告、`targets.py`、包根导出、
formal/development target 测试，并将实现映射到 G4B formal inference、G5B formal prediction、G7 上位
receipt SSOT 和共享 `ArtifactPublication`。生产代码与实现者测试保持只读；唯一新增文件是本报告。

本结论只针对 G7A 工程合同。Windows 与 WSL `/mnt/f` 绿测均不代表真实 G1 全折、真实数据性能、M3/M4
或 Linux/ext4 Gate 已通过；本机 WSL 文件系统实测为 `wslfs`。

## 2. 标准—证据—结论映射

| 合同项 | 核验证据 | 结论 |
|---|---|---|
| formal freshness | builder/verifier 各精确调用一次公开 prediction verifier 和 formal inference loader；fresh prediction 与传入 capability 比较 root/DataFrame/manifest/receipt 全身份 | 通过 |
| 完整域与顺序 | 独立不落盘探针覆盖 299/300/301 eligible domain；scorable/prediction exact 集合、`as_of,rank` prediction 顺序、`as_of,symbol` 完整 target 输出和 unselected/unscorable 显式零 | 通过（但见 Decimal 缺陷） |
| label/account 隔离 | formal 构建期间将 development 私有 feature reader 置为 hostile 仍成功；formal 路径无账户、持仓或订单入口 | 通过 |
| 身份与整包交叉 | 两套各自合法的完整 formal 上游 closure 交叉 verify 被稳定拒绝；fresh verifier 返回 bytes 相同但绝对 root 不同 capability 时在零 target 输出下拒绝 | 通过 |
| receipt | exact 14 inputs/3 outputs；stage/scope/key、duplicate/samefile alias、未知 input 与输出集合均有实现或测试约束 | 通过 |
| 不可变发布 | 复用 root lease、实体身份、exclusive create、owned identity、逆序回滚；已有输出 root replacement 和三阶段 writer 失败测试通过 | 通过 |
| 稳定错误 | 独立嵌套 hostile exception graph 被换译为固定错误，`cause/context is None`，marker 不泄漏 | 通过 |
| Decimal 数学 | 合法 `n_selected=7` 的未封顶分配被实现误判为超配 | **失败** |

## 3. 必须返工的问题

### [P1] 合法的循环小数等权分配被 Decimal 舍入尾差误拒

- **现象**：`cash_buffer=0.1`、`max_weight=0.2`、`n_selected=7` 时，冻结公式本应选择
  `(1-0.1)/7`。当前实现计算出的有限精度 Decimal 权重再乘 7 得
  `0.9000000000000000000000000002`，随后触发
  `formal target decimal allocation exceeds investable`。同一逻辑也存在于 development core。
- **根因**：实现把非终止十进制除法在当前 Decimal context 下的舍入结果再次乘回，并把最后一位舍入尾差
  当成真实超配。这个检查不等价于冻结的数学公式。
- **应遵循规则**：选中权重必须按
  `min((1-cash_buffer)/n_selected, max_weight)` 计算；合法 selector 和任意正整数选择数不得因为 Decimal
  表示精度而 fail closed。是否受 `max_weight` 封顶应依据公式分支判断，不能用非终止小数乘回后的尾差裁决。
- **最小复现**：构造单日 299 个 eligible、其中 298 个 scorable/predicted，rank 连续，`top_k=7`、
  `cash_buffer=0.1`、`max_weight=0.2`、coverage threshold 为 0；调用
  `_build_frames_from_layers(...)` 即抛上述错误。单独的算术核心为
  `Decimal("0.9") / Decimal(7) * Decimal(7) > Decimal("0.9")`。
- **必须新增测试**：formal artifact 至少增加 `top_k=7` 的未封顶非终止小数正例，断言完整 299 domain、
  7 个正权重、其余显式零、daily/manifest 计数正确且 build→receipt→verify 闭环成功；development 公共核心
  也应增加等价回归，防止两条路径漂移。
- **通过条件**：上述正例在 Windows 和 WSL base 均通过；现有 max-weight 封顶、cash-buffer、总权重不超配、
  writer rollback、whole-bundle/foreign closure 反例保持绿色；Ruff/mypy 通过。

## 4. 独立对抗结果

- `DOMAIN_299_300_301_PASS`：改用明确受 `max_weight=0.1` 封顶的控制组后，三种完整域均输出全部 eligible，
  每日选择 7 个，其余全部为零。
- `HOSTILE_GRAPH_PASS`：嵌套 `KeyError -> RuntimeError` 私有 marker 没有穿透 formal 边界。
- `CLOSURE_COPIED_ROOT_LABEL_ZERO_PASS`：合法不同上游 closure 交叉、copied-root fresh 返回均被拒绝；formal
  构建不调用 development 私有 feature reader。
- 实现者未覆盖的未封顶 `0.9/7` 控制变体稳定复现 P1，因此现有 formal 5 个绿测不足以接受数学合同。

## 5. 验证命令与实际结果

Windows 原生 Miniforge：

- formal G7A：`5 passed`，约 89 秒；
- development 直接节点（299/300/301、零权重、foreign whole bundle、轻导入）：`6 passed`，约 69 秒；
- Ruff：`All checks passed!`；
- mypy：`Success: no issues found in 2 source files`；
- 独立不落盘对抗：其余三组 PASS；`0.9/7` 合法未封顶正例按上述稳定失败。

WSL Miniforge `base`（`/mnt/f`）：

- formal G7A：`5 passed`，约 41 秒；
- 同组 development 直接节点：`6 passed`，约 31 秒；
- Ruff、mypy 均通过；
- `stat -f -c %T .`：`wslfs`，故仅为 WSL/DrvFS 兼容性证据。

两平台 pytest 只有 Pandera deprecation warnings 与无权写 `.pytest_cache` 的 cache warning，没有产品失败。
这些绿测不覆盖本报告新增的非终止 Decimal 分配反例。

## 6. 最终判定

G7A 的 freshness、完整域、formal/development 隔离、receipt 和事务发布主结构成立，但公共数学合同会拒绝一类
完全合法的 Top-k 配置，属于进入 G7B 前必须修复的正确性缺陷。本轮独立初验 **FAIL**；完成最小修复、加入
formal 与 development 回归并由未参与返工实现的新独立会话复验 PASS 后，方可进入主 Agent 最终验收。
