# M3 G8C-C0 F0 R5：fixture teardown 零残留观测返工任务单

日期：2026-08-11
状态：**外部独立复验与主 Agent 最终验收 PASS（2026-08-12）；R5 已关闭并恢复 C0，允许进入 C1。见 [独立复验](M3_G8C_C0_F0_R5_fixtureTeardown零残留观测独立复验报告.md) / [C0 主验报告](M3_G8C_C0_R3_配置原路径锚定与全链Integration主Agent最终验收报告.md)**
前置：[`M3_G8C_C0_F0_R4_ownedCleanup来源绑定独立复验报告.md`](M3_G8C_C0_F0_R4_ownedCleanup来源绑定独立复验报告.md) 已判定 **FAIL**；R4 的物理来源绑定对抗本身 PASS

## 1. 现象—根因—应遵循规则

- 现象：实现者与独立初验的最终 Windows honest public-chain 均为 `1 failed, 11 passed, 1 skipped`；失败节点 `test_formal_public_chain_owned_cleanup_zero_residuals` 观察到 stage/config/G1 仍存在且 `_LAST_OWNED_CLEANUP_REPORT == []`，进程退出后残留才归零。
- 根因：`formal_chain_locator` 是 module fixture，并在 `with public_formal_chain_session(...)` 内 `yield`；其 teardown 只能在整个测试模块结束后执行。独立的残留测试虽然不请求 fixture，仍运行在 module teardown 之前。15 秒轮询等待的是尚未发生的 cleanup，不能形成生命周期同步。
- 应遵循规则：零残留证据必须在 `public_formal_chain_session.__exit__` / `finally` 完成之后采集；不得用活 session、任意等待时间或 pytest 进程退出后的手工扫描代替。
- R4 已通过的安全不变量保持冻结：创建时 exact `(st_dev, st_ino, kind)`；`finally` 不刷新目录来源；文件/目录删除前双 `lstat`；same-path 不同实体、类型/link/reparse、检查异常 fail-safe。

## 2. 唯一最小实现方案

只调整 `formal_chain_locator` 的测试生命周期：

1. 在进入 `with public_formal_chain_session(...)` 后保存 stage root、session config、G1 release 三个 exact 路径，继续 `yield locator` 供现有五个 honest/hostile 节点复用。
2. 当 `yield` 返回后，让 `with` 正常退出；只有此时 `public_formal_chain_session.finally` 已完成 `_owned_cleanup`。
3. 紧接 `with` 块之后、仍在 fixture teardown 内执行零残留断言：
   - 三个 exact 路径均不存在；
   - `artifacts/research/m3/_f0r*` 为空；
   - `_LAST_OWNED_CLEANUP_REPORT` 非空，并分别包含三个 exact `removed:{path}`。
4. 删除独立的 `test_formal_public_chain_owned_cleanup_zero_residuals` 与 `_wait_path_gone`；禁止保留或增加轮询、sleep、进程退出后扫描。
5. teardown 断言失败必须使 pytest 非零退出并附着到使用该 module fixture 的官方测试生命周期；不得捕获、降级为 warning 或只写日志。

不得改 fixture scope、不得重复构建真实 G1 链、不得拆出第二个测试模块、不得修改 `public_formal_chain_session` / `_owned_cleanup` 或任何 production。若 pytest 无法让 teardown 断言可靠影响退出码，立即停止并报告，不自行扩大设计。

## 3. 必测反例与回归

1. 快速生命周期探针证明：`yield` 期间路径存在且 report 仍空；退出 `with` 后路径消失且 report 含三个 `removed:`。探针不得构建真实 G1，也不得伪造 production capability/verifier。
2. R4 六个 cleanup 快速节点全部保留并通过：directory/file ABA、不刷新、类型/link、正常清理、检查异常。
3. 最终 Windows honest public-chain 在最终 revision 上只启动一次，给足 7200 秒；预期 `11 passed, 1 skipped`、EXIT=0，teardown 零残留断言实际执行。
4. 最终进程内证据必须来自 fixture teardown；不得以命令结束后的另一次扫描补充成 PASS。
5. WSL base：capability=False，cleanup 快速节点与 skip 边界通过；DrvFS/wslfs 仅兼容证据，非 ext4 Gate。
6. 定向 Ruff、mypy、cold import、scoped diff/whitespace 与白名单检查通过。

## 4. 文件白名单

允许修改：

- `tests/integration/test_m3_g8c_c0_formal_cli_resolve.py`
- `docs/agent/M3_G8C_C0_F0_R4_ownedCleanup来源绑定返工任务单.md`（仅状态/链接）
- `docs/agent/M3_G8C_C0_F0_R3_续跑Provider至Resolver任务单.md`（仅状态/链接）
- 本任务单（仅状态）
- 唯一交付报告：`docs/agent/M3_G8C_C0_F0_R5_fixtureTeardown零残留观测返工交付报告.md`

独立初验仅允许新增：`docs/agent/M3_G8C_C0_F0_R5_fixtureTeardown零残留观测独立复验报告.md`。

禁止修改 `tests/support/m3_formal_public_chain/session.py`、`src/`、其余 support/tests/config、既有报告、正式 `data/`/长期 artifact、其他工作树；禁止联网、add/commit/push；不得使用 fake verifier、private issuer、`SimpleNamespace`、`object.__new__/__setattr__` 或 replace verified capability。

## 5. 外部闭环与通过条件

- 实现必须使用全新 `cursor-agent --model auto` 会话；只按白名单修改并提交压缩交付报告，不得宣布 Gate。
- 实现完成后必须由未参与 R5 实现的另一全新 `cursor-agent --model auto` 会话独立初验；生产、support 和实现测试只读，只写唯一复验报告，并补一个实现者未使用的 teardown 顺序探针。
- 独立初验 PASS 后才允许主 Agent 主验；主验通过也只关闭 F0 R5 / 恢复 C0，不代表 C1/G8C/M3/ext4 Gate PASS。
- 任一最终长链非零、teardown report 为空、三路径或 `_f0r*` 残留、R4 ABA 回归失败、越白名单或需修改 support/production，均判 FAIL 并重新进入实现—独立初验闭环。
