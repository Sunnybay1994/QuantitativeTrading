# M3 G8C-C0 F0 R4：owned cleanup 来源绑定返工任务单

日期：2026-08-11  
状态：**历史独立初验 FAIL 已由 R5 最小返工关闭；R5 独立复验与主 Agent 最终验收均 PASS（2026-08-12）。见 [R5 独立复验](M3_G8C_C0_F0_R5_fixtureTeardown零残留观测独立复验报告.md) / [C0 主验报告](M3_G8C_C0_R3_配置原路径锚定与全链Integration主Agent最终验收报告.md)**
前置：[`M3_G8C_C0_F0_R3_ownedCleanup来源专项外部审计报告.md`](M3_G8C_C0_F0_R3_ownedCleanup来源专项外部审计报告.md) 已判定 **FAIL/P0**

## 1. 现象、根因与被破坏的不变量

- 现象：session-owned 目录被 rename 后，在同一路径创建不同 inode 的 foreign 目录与 sentinel；R3 `finally` 会删除 foreign 目录。
- 根因：
  1. `public_formal_chain_session.finally` 在 cleanup 前刷新所有目录 token，把 foreign 目录重新登记成 owned；
  2. `_owned_cleanup` 只在 `path.is_file()` 时检查 token 漂移，目录即使来源已变仍进入 `shutil.rmtree`。
- 即使去掉刷新，第二项也会继续误删 foreign 目录；因此不得只删 refresh 循环而保留“仅文件校验”。
- 应遵循规则：清理权限来自“本 session 创建的 exact 物理实体”，不来自逻辑路径字符串。任何 same-path 不同实体、symlink/junction/reparse 或无法稳定验真的目标都必须保留并报告，绝不递归删除。

## 2. 最小返工目标

只收紧 `tests/support/m3_formal_public_chain/session.py` 的 owned-entity 记录与清理，并补正式回归：

1. 创建文件或目录后立即记录不受内容/子项变化影响的物理实体身份；目录正常写入子文件不得造成误判。
2. cleanup 前不得把当前 same-path 实体重新登记为 owned；禁止刷新目录来源身份。
3. 文件与目录删除前都必须用 `lstat` 重验 exact 原实体；实体漂移、类型漂移、link/reparse、缺失或检查异常均 fail-safe，不删除当前路径。
4. 普通成功、普通异常及 hostile 测试恢复后的 session-owned config/G1/stage 根仍应完整清理，不留下 `_f0r*`、session config 或 G1 release。
5. 不改变真实 public G1→backtest_plan→resolver 链、verifier 顺序、Windows 环境 gate、WSL skip 或任何 production API。

实现可以调整私有 token 类型/辅助函数；不得引入通用清理框架、后台线程或第三方依赖。若 Windows 无法用稳定 `lstat` 身份区分 same-path 目录替换，立即停止并报告，不得退化为路径信任。

## 3. 必须新增的正式测试

在不启动完整 G1 链的快速节点中至少覆盖：

1. **目录 ABA**：记录 owned dir → rename 到旁路 → same path 新建 foreign dir+sentinel → cleanup；foreign 与 sentinel 必须保留，报告必须为 changed/special skip。探针结束后测试自己精确清理两边临时目录。
2. **不刷新仍安全**：证明严格目录 identity 是必要条件；不能只依赖移除 refresh。
3. **文件 ABA**：owned config/file 被 same-path 新 inode 替换时不得删除 foreign file。
4. **类型/link 漂移**：目录换成文件、文件换成目录，以及平台允许时 symlink/junction/reparse，均不得删除或跟随。
5. **正常对照**：未漂移的 owned file/dir 能被删除；目录内部正常增加 session 产物不影响 root identity。
6. **真实链 cleanup**：最终 Windows honest public-chain integration 自然结束后，owned config、stage root、G1 release 与 `_f0r*` 残留均为零。

测试不得依赖 private production issuer、fake verifier、`SimpleNamespace`、`object.__new__/__setattr__`、replace verified 或 production monkeypatch。

## 4. 文件白名单

允许修改：

- `tests/support/m3_formal_public_chain/session.py`
- `tests/integration/test_m3_g8c_c0_formal_cli_resolve.py`
- `docs/agent/M3_G8C_C0_F0_R3_续跑Provider至Resolver任务单.md`（只更新状态/链接）
- 本任务单（只更新状态）
- 唯一交付报告：`docs/agent/M3_G8C_C0_F0_R4_ownedCleanup来源绑定返工交付报告.md`

禁止修改：

- `src/` 全部 production；
- 其余 support、tests、config、pyproject/lock、既有交付/独立初验/专项审计报告；
- 正式 `data/`、长期 artifact、任何其他 worktree。

禁止联网、add、commit、push；禁止与仍运行的 R3 原独立初验会话并发写同一文件。

## 5. 验证顺序与通过条件

1. Windows `D:\Miniforge3\envs\m3chain312\python.exe` 先跑新增 cleanup 快速节点。
2. Ruff：修改的 support 与 integration test。
3. mypy：同两文件，沿用 F0 R3 的 `PYTHONPATH/MYPYPATH=src` 与 `--follow-imports=silent`。
4. cleanup 快速节点通过后，Windows actual integration 只启动一次，最长 7200 秒；不得并发或重复长链。
5. WSL base 只跑 capability/skip 与 cleanup 快速节点；DrvFS 不宣称 ext4 Gate。
6. cold import、scoped `git diff --check`、残留扫描。

全部通过且满足以下条件才可交独立复验：

- 专项报告的 directory ABA 最小复现关闭；
- foreign file/dir/link 从未被 cleanup 删除；
- 正常链 owned roots 仍能清净回收；
- public chain/resolve 结果与 R3 不变；
- 没有生产改动、越白名单或正式数据写入。

## 6. 独立复验要求

实现完成后必须交给未参与 R4 实现的全新 Cursor Agent 会话，并按用户最新指令使用 `--model auto`。独立复验至少使用一个实现者未采用的 same-path directory replacement 时序，并检查 cleanup 报告、foreign sentinel、普通清理对照、双平台静态/skip 和一次最终 Windows honest chain。初验 PASS 后仍需主 Agent 终验；不得因此宣布 C0/C1、G8C、M3 或 ext4 Gate 通过。
