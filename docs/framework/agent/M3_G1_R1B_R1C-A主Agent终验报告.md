# M3 G1 R1B / R1C-A 主 Agent 终验报告

日期：2026-07-16  
结论：**不通过，退回外部实现—独立初验闭环**  
范围：R1B 可恢复工作流服务、R1C-A 分阶段 CLI；不评价并行中的 M4-C0  
声明：不关闭 B4/G1/M3 Gate，不勾选路线图，不授权 R1C-B 真实运行

## 1. 已复核证据

- 任务书：`M3_G1_R1B可恢复工作流服务骨架外部闭环任务单.md`、`M3_G1_R1C分阶段CLI与真实全量运行外部闭环任务单.md`。
- 外部闭环：R1B 实现、首次初验不通过、返工、独立复验通过；R1C-A 实现与独立初验通过。
- 主验定向：
  - `tests/unit/test_m3_run_g1.py`：**25 passed / 2.15s**；
  - R1B 快速合同/路径/脱敏/import 子集：**9 passed / 3.00s**；
  - R1B/R1C 白名单文件 Ruff：**通过**；
  - 两个生产模块 mypy：**通过**。
- 未运行主验全量 pytest：M4-C0 正在并行写入，且本轮已由下述最小反例确定不通过；不把并发工作树的瞬态结果混入本包结论。外部初验已有 `851 passed + 1` 个孤立复跑通过的 journal-lock flake 基线，但不能替代返工后的全量回归。

## 2. 主验新增反例

### P0-A：`VerifiedG1WorkflowStateV1` 不自证阶段—产物—counts 闭包

- 位置：`src/quant/research/m3/g1_workflow.py:208`，`__post_init__` 自 `:221`。
- 现象：对 fresh inspect 的合法 state 执行：

  ```python
  dataclasses.replace(state, completed_stages=("INDEX", "HISTORY"))
  ```

  构造成功；实测输出为 `R1B_INVALID_ACCEPTED ('INDEX', 'HISTORY') True 0`，即声称 HISTORY 完成，但 `candidate is None`、`history_requests == 0`、没有 history verified responses。
- 根因：值对象只校验 exact type 和阶段前缀，没有校验任务书 §7/§9.2 冻结的阶段、产物、计划 totals 与 response 集合关系。
- 破坏的不变量：名字为 `Verified*` 的公开对象可以携带互相矛盾的证据；R1C/G2 不能安全依赖其完成阶段和 identity 生命周期。
- 判定：**P0，阻断 R1B 主验**。

### P0-B：`G1CliResultV1` 不自证 identity 出现条件与裸 hex

- 位置：`src/quant/research/m3/run_g1.py:123`，`__post_init__` 自 `:138`。
- 现象：`completed_stages=()` 时同时传入 `primary_candidate_key="not-hex"`、`release_id="too-early"`、`manifest_sha256="also-not-hex"`，构造成功。
- 根因：只校验 stage 前缀、非负 counts 和 error_code 集合；没有实现任务书 §5/§6.1 明文要求的 digest 裸 64 hex、identity 生命周期、成功/失败字段闭包及 `error_operation` allowlist。
- 破坏的不变量：CLI 可以输出 schema 合法表象下的虚假 SUCCESS/identity，后续自动化无法只凭结果对象验真。
- 判定：**P0，阻断 R1C-A 主验**。

### P1-C：CLI 接受项目外配置文件

- 位置：`src/quant/research/m3/run_g1.py:466`。
- 现象：把合法示例 TOML 复制到系统临时目录、项目根位于另一目录时，`_validate_config_path(outside)` 返回 `LoadedM3Config`；实测 `R1C_OUTSIDE_CONFIG_ACCEPTED LoadedM3Config`。
- 根因：函数只检查 exists / 末端 symlink / regular file，不接收 `project_root`，无法证明配置位于项目内，也不检查祖先 symlink/读取前后物理身份。
- 应遵循规则：R1C 任务书 §3 的 `--config` 必须为项目内普通非 symlink TOML；路径失败必须稳定映射 `CLI_CONFIG_INVALID`，不得泄露路径。
- 判定：**P1，阻断 R1C-A 主验**。

### P1-D：合法 command 在后续 argparse 失败时被错误清空

- 位置：`src/quant/research/m3/run_g1.py:659`；现有 `test_argparse_rejects_token_and_unknown` 固化了错误期望。
- 现象：参数中已经出现合法 `status`，随后出现未知 `--version 9`，结果仍为 `command=None`。
- 根因：`parse_args` 任意失败统一走同一分支，没有保留已经可无歧义识别的 command literal。
- 应遵循规则：R1C 任务书 §5：尚未得到合法 command 才能为 `None`；一旦识别，后续失败必须保留该 literal。
- 判定：**P1，阻断 R1C-A 主验**。

## 3. 非阻断记录

R1C 独立初验发现 stdout partial-write 时 `OSError` 外溢且可能留下截断 JSON。物理流已部分写入后无法保证重新输出完整单行 JSON，因此本轮不把它扩成 P0/P1；返工可做最小加固：单次 write、捕获写错误、exit 2、best-effort 稳定 stderr、不输出 traceback，不尝试在同一已损坏流伪造第二份 SUCCESS/FAILED JSON。

## 4. 结论与下一步

已有定向测试、Ruff、mypy 绿色，但未覆盖任务书的自证与路径边界。R1B/R1C-A 保持**待主验且本轮不通过**，必须按 [`M3_G1_R1B_R1C-A主验返工任务单.md`](M3_G1_R1B_R1C-A主验返工任务单.md) 回到外部实现，再由未参与返工的全新 Grok High 会话独立初验。初验通过后再交主 Agent 复验；在此之前不启动 R1C-B。
