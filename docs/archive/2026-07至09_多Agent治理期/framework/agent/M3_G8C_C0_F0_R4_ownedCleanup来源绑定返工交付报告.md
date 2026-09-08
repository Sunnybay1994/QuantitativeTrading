# M3 G8C-C0 F0 R4：owned cleanup 来源绑定返工交付报告

日期：2026-08-11  
角色：外部实现 Agent（模型 `auto`；不声称具体底层模型；全新上下文）  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`  
任务单：[M3_G8C_C0_F0_R4_ownedCleanup来源绑定返工任务单.md](M3_G8C_C0_F0_R4_ownedCleanup来源绑定返工任务单.md)  
权威 P0：[M3_G8C_C0_F0_R3_ownedCleanup来源专项外部审计报告.md](M3_G8C_C0_F0_R3_ownedCleanup来源专项外部审计报告.md)  
前置说明：R3 独立复验 public-chain PASS **不取消** directory ABA P0。  
结论：**tests-support 最小返工已交付并完成实现自测；待全新独立复验。不宣称 C0/C1/G8C/M3/ext4 Gate PASS。**

## 1. 白名单与实际改动

| 路径 | 处置 |
|---|---|
| `tests/support/m3_formal_public_chain/session.py` | 创建后立即绑定 `(st_dev, st_ino, kind)`；`finally` **不再刷新** token；文件与目录删除前均 `lstat` exact 重验；漂移/link/reparse/检查异常 fail-safe 保留 |
| `tests/integration/test_m3_g8c_c0_formal_cli_resolve.py` | 目录 ABA、不刷新仍安全、文件 ABA、类型/link 漂移、正常对照、检查异常、真实链残留回归 |
| R3 任务单 | 仅状态/链接：public-chain PASS 不取消 P0，指向 R4 |
| 本 R4 任务单 | 仅状态 → 实现自测完成待全新独立复验 |
| 本交付报告 | 新增 |

未改 `src/`、其余 support/tests/config、既有报告、正式 `data/`/长期 artifact、其他 worktree。未联网、未 add/commit/push。未 monkeypatch production verifier/issuer。

support 四模块行数：15+60+339+817=**1231**（仍 4 模块）。

## 2. 冻结合同如何落地

- 身份不含 mtime：目录内正常增写 session 产物、hostile 恢复后的同 inode config 仍可删除。
- `finally` 只调用 `_owned_cleanup(owned_tokens)`，禁止把 same-path 当前实体重新登记为 owned。
- 删除前二次 `lstat`；`skip-changed-dir/file`、`skip-type-drift`、`skip-special`、`skip-check-error`、`missing` 均不删当前路径。
- Windows 启动前探针：same-path 目录/文件替换 **inode 可区分**（owned≠foreign）；未退化到路径信任。
- 目录 `rmtree` 后对 **同一 inode** 空根做短重试 `rmdir`，避免 Windows 根目录短暂残留被当成未清理。

## 3. 验证终态（诚实）

| 检查 | 终态 | 墙钟 | 说明 |
|---|---|---|---|
| Windows `m3chain312` cleanup 快速节点（首轮） | **6 passed**, 7 deselected；EXIT=0 | pytest 4.20s / shell 5950ms | `-k test_owned_cleanup_`；含 directory/file ABA、不刷新、类型/link、正常对照、lstat 异常 |
| Windows Ruff（两文件） | All checks passed；EXIT=0 | 265ms | 修改后复跑仍绿 |
| Windows mypy `--follow-imports=silent`，`PYTHONPATH/MYPYPATH=src` | 首轮 **FAIL**（`os.fspath(object)`）；修复后 **Success: 2 source files**；EXIT=0 | 2671ms | **首次失败**：integration hostile `lstat` 注解；已修，未重跑长链 |
| Windows actual integration（**只启动一次**） | **1 failed, 11 passed, 1 skipped**；EXIT=1 | pytest **6797.42s** / shell 6800.9s（<7200） | 见 §4 |
| WSL base capability + cleanup 快速 | capability=`False`；**7 passed**, 6 deselected；EXIT=0 | ~2.2s / 复跑 2.05s | `stat -f`=`wslfs`，`findmnt`/`df -T`=**drvfs**；**非 ext4**；不宣称 Gate |
| cold import | PASS；无 `qlib`/`lightgbm`/`mlflow`/`lgb` | 3706ms；复跑仍 PASS | formal_cli_resolve + 四 support |
| scoped `git diff --check` | EXIT=0（白名单在本 worktree 为 untracked，对 index 无 diff） | — | 另做空白扫描 **WHITESPACE_OK** |
| 残留扫描（实现结束后） | `_f0r*`=0；session config 不存在；`data/clean/m3_g1/releases` 为空 | — | 长链结束后即时复查 |

解释器：exact `D:\Miniforge3\envs\m3chain312\python.exe`，cwd=本 worktree，`PYTHONPATH=src`。  
WSL：`/home/mabw/miniforge3/bin/conda run -n base`，cwd=`/mnt/f/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g4-formal`。

## 4. 唯一一次 Windows 长链：首次失败

命令（未并发、未重跑）：

```text
$env:PYTHONPATH='src'
D:\Miniforge3\envs\m3chain312\python.exe -m pytest tests/integration/test_m3_g8c_c0_formal_cli_resolve.py -q --tb=line
```

- 输出：`...........sF`
- **11 passed**：6 个 cleanup 快速节点 + 5 个既有 public-chain/hostile（resolve 结果与 R3 合同节点绿）
- **1 skipped**：`test_wsl_capability_gate_skips_before_chain_writes`（win32 skip；非 PASS）
- **首次失败**：`test_formal_public_chain_owned_cleanup_zero_residuals`  
  断言 `stage_root.exists()` 为 True：  
  `artifacts/research/m3/_f0r2_f824702e79bb`
- 长链结束后只读复查（未再启动链）：该 stage root、session config、G1 release、`_f0r*` **均已不存在**。
- 判断：publisher 只在 owned `stage_root` 内 mkdir/rename 子树，不替换根 inode；更像 Windows 删除后根目录短暂可见。按任务书 **未第二次启动** actual integration。
- 随后仅收紧残留检查（15s 有界等待 + `_LAST_OWNED_CLEANUP_REPORT` 必须含三处 `removed:`）和同 inode 空根 `rmdir` 重试；快速节点/Ruff/mypy/WSL 已复验绿。

## 5. Skip 边界

- Windows WSL capability 测试：skip（actual 由 fixture 覆盖）。
- WSL 上 `public_formal_chain_session`：capability=false，写前 skip；cleanup 快速节点在 DrvFS 上可跑且绿。
- 类型/link 漂移：本机 Windows 成功创建 directory symlink/junction，未 skip 该分支。
- 若 `lstat` 无法区分 same-path 替换：测试 `_require_distinct_inode` 会 **RuntimeError 停止**，不退回路径信任。本轮未触发。

## 6. 禁止项自检

| 项 | 本轮 |
|---|---|
| production / verifier / issuer monkeypatch | 未做 |
| fake verifier / private issuer / SimpleNamespace / replace verified | 未做 |
| 联网 / add / commit / push | 未做 |
| 正式 data / 长期 artifact / 其他 worktree | 未写 |
| 重复或并发长链 | **未做**（失败后只做快速节点与静态复查） |

## 7. 给独立复验

- 必须全新会话、`--model auto`。
- 至少使用一个实现者未采用的 same-path directory replacement 时序。
- 自己跑 cleanup 快速节点 + **一次** Windows honest public chain；核对 cleanup report、foreign sentinel、普通清理对照、双平台静态/skip。
- R3 public-chain PASS 与本轮 fixture 5 个链上节点绿，均不取消 directory ABA P0，也不等于 C0/C1/ext4 Gate。
