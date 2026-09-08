# M3 G8C-C0 F0 R4：owned cleanup 来源绑定独立复验报告

日期：2026-08-11  
角色：外部独立初验 Agent（模型 `auto`；不声称具体底层模型；未参与 R4 实现的全新上下文）  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`  
解释器：exact `D:\Miniforge3\envs\m3chain312\python.exe`（`PYTHONPATH=src`；cwd=本 worktree）  
任务单：[M3_G8C_C0_F0_R4_ownedCleanup来源绑定返工任务单.md](M3_G8C_C0_F0_R4_ownedCleanup来源绑定返工任务单.md)  
交付报告：[M3_G8C_C0_F0_R4_ownedCleanup来源绑定返工交付报告.md](M3_G8C_C0_F0_R4_ownedCleanup来源绑定返工交付报告.md)  
权威 P0：[M3_G8C_C0_F0_R3_ownedCleanup来源专项外部审计报告.md](M3_G8C_C0_F0_R3_ownedCleanup来源专项外部审计报告.md)  
UA-AGENT-001：已批准；未接触 token/账号/私密配置/受许可原始数据/正式 data 内容。

## 结论

**FAIL** — 不得进入主验。  
不宣称 C0/C1、G8C、M3 或 ext4 Gate PASS。  
实现者历史长链 `11 passed / 1 skipped / 1 failed` **不得**当作本轮 PASS；本会话在最终代码上只启动一次 Windows honest public-chain，复现同类失败。

身份绑定与 directory ABA 快速/独立探针本身为绿，但不能覆盖任务书第 3.6 / 第 5.4 条「真实链 cleanup 官方节点」合同。

## 1. 角色与只读边界

- 生产、`tests/support`、实现者测试、任务书与既有报告：**只读**。
- 唯一写入：本报告。
- 独立探针仅系统 TEMP，结束后脚本与目录均已删除；`TEMP_LEFTOVER=0`。
- 未联网、未 add/commit/push、未写正式 `data/` / 长期 artifact、未触其他 worktree。
- 未改 production verifier/issuer；未使用 fake verifier / private issuer / `SimpleNamespace` / `object.__new__` / replace verified。

## 2. 标准—证据—结论（逐项）

| 冻结项 | 独立证据 | 结论 |
|---|---|---|
| 创建后立即绑定 `(st_dev, st_ino, kind)`，不含 mtime | `session.py` `_entity_token` / `_record_owned`；目录内增写后 token 不变（实现者正常对照 + 本会话独立探针） | **PASS** |
| `finally` 禁止刷新目录来源 | `finally` 仅 `_LAST_OWNED_CLEANUP_REPORT[:] = _owned_cleanup(owned_tokens)`；无 `_entity_token` / `owned_tokens[` 赋值。实现者 `test_owned_cleanup_directory_identity_required_without_token_refresh` 源码断言成立 | **PASS** |
| 文件与目录删除前 `lstat` exact 重验 | `_owned_cleanup` 两次 `os.lstat`；`kind` / `(dev,ino)` / link-reparse 任一失配则 skip，不删 | **PASS** |
| same-path 不同实体 / 类型漂移 / link-reparse / 检查异常 fail-safe | 实现者 6 个快速节点绿；独立探针见 §4 | **PASS** |
| 正常 owned 根及内部新增产物仍可清理 | 快速节点 `removed:`；独立探针 aside 原 inode 可删 | **PASS** |
| Windows 无法区分 inode 时停止、不退回路径信任 | `_require_distinct_inode`；本机 owned≠foreign，未触发 RuntimeError | **PASS** |
| 真实链 cleanup 后 config / stage / G1 / `_f0r*` 为零，且 report 含三处 `removed:` | 最终长链官方节点失败，见 §5 / §6 | **FAIL** |
| 白名单 / 无本会话生产改动 / 无正式数据写入 | 本会话未改 `src/` 或测试。工作树存在**对话开始即已存在**的 `src/` 脏状态，非本复验写入 | **本会话遵守**；跨 Gate 脏树交主验知悉 |
| support 仍 4 模块且 ≤1300 | 15+60+339+817=**1231** | **PASS**（范围核） |

## 3. 快速节点 / 静态 / WSL（先于长链）

解释器：`D:\Miniforge3\envs\m3chain312\python.exe`。  
WSL：`/home/mabw/miniforge3/bin/conda run -n base`，cwd=`/mnt/f/AI_Coding/QuantitativeTrading/artifacts/dev_worktrees/m3-g4-formal`。

| 检查 | 终态 | 墙钟 | 首次失败 / skip |
|---|---|---|---|
| Windows `-k test_owned_cleanup_` | **6 passed**, 7 deselected；EXIT=0 | pytest 3.66s / shell 5796ms | 无失败。`.pytest_cache` WinError 5（非本任务写入） |
| Windows Ruff（两文件） | All checks passed；EXIT=0 | 278ms | 无 |
| Windows mypy `--follow-imports=silent`，`PYTHONPATH/MYPYPATH=src` | Success: 2 source files；EXIT=0 | 2811ms | 无（相对实现者首轮 mypy FAIL，本轮最终代码已绿） |
| cold import（`formal_cli_resolve` + 四 support） | PASS；`qlib`/`lightgbm`/`mlflow`/`lgb` 均未冷导入 | 5374ms | 无 |
| scoped `git diff --check`（tracked） | EXIT=0（白名单代码对 index 为 untracked） | — | `git diff --check --no-index NUL <file>` 因 CRLF 提示 EXIT=1，**不**当作空白错误 |
| Python 空白扫描两文件 | **WHITESPACE_OK** | — | 无 |
| WSL fstype | `stat -f`=`wslfs`；`findmnt`/`df -T`=**drvfs**；**非 ext4** | 含在 WSL 总墙钟 | 不宣称 ext4 Gate |
| WSL capability | `platform_supports_renameat2_noreplace()=False`；`sys.platform=linux` | 同上 | skip 语义，非 PASS |
| WSL `-k "test_owned_cleanup_ or test_wsl_capability_gate"` | **7 passed**, 6 deselected；EXIT=0 | pytest 2.33s / WSL 命令约 28.8s | capability 节点在 Linux 上执行并在写前 skip session；非长链 |

长链前残留：`_f0r*` 无；session config 不存在；`data/clean/m3_g1/releases` 为空。

## 4. 独立对抗（实现者未用时序）

实现者 directory ABA：`mkdir owned → rename aside → 同路径再 mkdir → 写 sentinel`。  
本会话 TEMP 探针（`%TEMP%\m3_g8c_c0_f0_r4_indep_adv.py`，跑完已删）改用：

1. **预建完整 foreign 树后 `rename` 覆盖到腾空路径，再二次 hop 换成另一棵 foreign 树**（非 in-place mkdir）  
2. 文件 **unlink + 重建**（实现者用 rename）  
3. 目录腾空后把 **文件 rename 到原路径**（类型漂移）  
4. 腾空路径上建 **junction** 指向含 sentinel 的真目录  
5. `missing:` / `skip-unbound:` 对照  
6. 原 owned aside 用创建时 token 清理，证明正常回收仍可用

| 案 | 结果 |
|---|---|
| prebuilt rename-onto + second hop | foreign/sentinel 保留；`skip-changed-dir:`；aside `removed:` |
| file unlink+recreate | foreign 保留；`skip-changed-file:` |
| file-onto-dir rename | 文件保留；`skip-type-drift:` |
| junction-onto-vacated | junction 与 target sentinel 保留；`skip-special:`；**未 skip 该分支** |
| unbound / missing | `skip-unbound:` / `missing:`；未删现目录 |

- 首次探针失败：`FileNotFoundError`（探针未 `mkdir` 父目录 `c1`）——**探针编排错误，非产品缺陷**。  
- 补 `parents=True` 后 **INDEP_ADV_PASS**；EXIT=0；墙钟 4145ms；`TEMP_LEFTOVER=0`。

## 5. 唯一一次 Windows honest public-chain

确认无并发 `m3chain312`/`formal_cli_resolve` pytest 后启动；未重跑、未并发。

```text
$env:PYTHONPATH='src'
D:\Miniforge3\envs\m3chain312\python.exe -m pytest tests/integration/test_m3_g8c_c0_formal_cli_resolve.py -q --tb=line
```

| 字段 | 实测 |
|---|---|
| 启动 | 2026-08-11T19:11:40+08:00 |
| 结束 | 2026-08-11T21:07:33+08:00 |
| pytest 墙钟 | **6949.56s**（1:55:49，<7200） |
| shell elapsed | 6959020ms |
| 输出 | `...........sF` |
| 摘要 | **1 failed, 11 passed, 1 skipped**, 198746 warnings |
| EXIT | **1** |
| 首次 skip | `test_wsl_capability_gate_skips_before_chain_writes`（win32 skip；非 PASS） |
| **首次失败** | `test_formal_public_chain_owned_cleanup_zero_residuals` |
| 失败断言 | `{'stage_exists': True, 'config_exists': True, 'g1_exists': True, 'cleanup_report': []}` |
| 11 passed | 6 cleanup 快速节点 + 5 个 public-chain/hostile（resolve 合同节点绿） |
| 长链后残留复查（21:08:40，未再启动链） | `_f0r*`=0；session config 不存在；G1 releases 为空 |

实现者旧长链失败后「只读复查已消失」与本轮一致，**不能**把事后清空写成官方节点 PASS。

## 6. 现象—根因—规则—最小复现—新增测试—通过条件

### 现象

最终 Windows honest public-chain 官方残留节点失败：module fixture 仍持有 session 时，`stage_root` / session config / G1 release **三者仍存在**，且 `_LAST_OWNED_CLEANUP_REPORT == []`。15s `_wait_path_gone` 不能改变该观察。进程退出后 `finally` 才清理，事后扫描为零残留。

### 根因

1. `formal_chain_locator` 为 **module** fixture，在 `with public_formal_chain_session` 内 `yield`；`finally` / `_owned_cleanup` 只在 fixture teardown 执行。  
2. `test_formal_public_chain_owned_cleanup_zero_residuals` **不请求**该 fixture，却与使用 fixture 的测试同模块。  
3. 本机 pytest 对 module fixture 的 teardown 发生在**模块全部测试之后**，包括不使用该 fixture 的测试。因此残留测试读到的是**尚未 cleanup 的活 session**：路径仍在、report 仍是模块初值 `[]`。  
4. 实现者把同文件失败解释为 Windows `rmtree` 后根目录短暂可见，并加 15s 等待与同 inode `rmdir` 重试。该解释与 **`cleanup_report=[]`** 矛盾——`finally` 当时尚未写入 report，等待无法观测尚未发生的删除。

身份绑定返工（禁止 refresh、目录也做 exact `lstat`）**不能**被本失败否定；失败点是「真实链 cleanup 官方观测窗口」放在 teardown 之前。

### 应遵循规则

- 清理权限仍须绑定创建时 exact `(dev, ino, kind)`；本条已在快速/独立探针成立。  
- **真实链零残留证据必须取自 `public_formal_chain_session.finally` 之后**，不得在活 session 上把「路径仍存在」判为 cleanup 失败，也不得用进程退出后的手工扫描代替官方节点。  
- 15s 轮询不能代替 fixture 生命周期同步。

### 最小复现

TEMP 探针（已删）镜像同序：

```text
module fixture: setup → yield → (teardown 在模块末尾)
test_user(fixture)
test_skipper()          # 不请求 fixture
test_residual_like()    # 不请求 fixture；此时 teardown 未发生
```

实测事件：`['setup', 'user', 'skipper', 'residual_seen:setup,user,skipper']`，无 `teardown`。  
`1 failed, 2 passed`；墙钟 2.88s / 4187ms。与长链 `cleanup_report=[]` 同构。

### 必须新增的测试 / 观测

不得再让残留断言跑在 module fixture teardown 之前。至少择一：

1. 在 fixture **`with` 块之后**（`yield` 返回后、cleanup 已执行）采集 `exists` + `_LAST_OWNED_CLEANUP_REPORT`，用 teardown 失败或单独后置节点暴露；或  
2. 将残留节点放到**后收集的另一测试模块**，确保 chain 模块 teardown 已完成；或  
3. 提供显式 post-cleanup snapshot fixture，**先**结束 session 再 `yield` 快照给残留测试。

残留测试若改为请求 `formal_chain_locator`，测试体仍在 teardown 前，会更糟。  
实现者 15s 等待 **不是**充分修复。

### 通过条件

1. 最终代码上 **只启动一次** Windows honest public-chain；官方残留节点 PASS。  
2. 该节点观察到的 report 非空，且含 `removed:{stage_root}` / `removed:{config}` / `removed:{g1_root}`。  
3. 断言时三路径已不存在；`_f0r*` 为零。  
4. 不得依赖「pytest 进程退出后再手工扫描」。  
5. 既有 directory/file ABA、不刷新、类型/link、正常清理、独立 rename-onto 时序仍绿。  
6. 通过后仍只解锁主验，不宣布 C0/C1/G8C/M3/ext4。

## 7. 禁止项与范围

| 项 | 本轮 |
|---|---|
| 本会话改 production / 实现者测试 | 无 |
| 联网 / add / commit / push | 无 |
| 正式 data / 长期 artifact / 其他 worktree | 无 |
| 重复或并发长链 | **无**（仅 19:11:40 一次） |
| 把实现者 11/1/1 当 PASS | **无** |
| 工作树既有 `src/` 脏文件 | 对话开始已存在；非 R4 白名单、非本会话写入 |

## 8. 非声明

- **不可**声明独立初验 PASS，**不可**进入主验。  
- **不可**宣称 C0 resolver / C1 / G8C / M3 / Linux·ext4 Gate PASS。  
- WSL 本轮仅为 DrvFS capability/skip + cleanup 快速节点。  
- 身份绑定快速合同绿，不取消本报告对真实链官方残留节点的 FAIL。
