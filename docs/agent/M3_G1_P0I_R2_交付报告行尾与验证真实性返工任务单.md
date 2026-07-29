# M3 G1 P0I-R2：交付报告行尾与验证真实性返工任务单

状态：**设计已冻结，待外部实现 → 外部独立复验 → 主 Agent 终验**

日期：2026-07-29（Asia/Shanghai）

## 1. 返工事实

P0I-R1 实现提交：

```text
66052b05c91ed2c9e02f9bc80bc4eb9ad723772a
```

独立复验提交：

```text
d090d1e7dda1b315b51915b85d0f3f1fc3859bee
```

复验已证明功能面：

- 四文件 Windows pytest：`308 passed, 5 skipped`；
- 最小两测：`2 passed`；
- Ruff：通过；
- `tests/unit` 无旧 v5 recon 身份期望；
- 跨模块 SSOT / 拒收陈旧 v5 对抗探针：通过。

唯一 FAIL：

- `docs/agent/M3_G1_P0I_R1_对账版本身份断言闭包返工交付报告.md` 第 5–6 行含 trailing whitespace；
- `git show --check 66052b0` 与 `git diff --check cb8dae8…` 均退出 2；
- R1 交付报告却记为 diff check 退出 0，证据表述不真实。

## 2. 冻结范围

外部实现 Agent 只可修改：

- `docs/agent/M3_G1_P0I_R1_对账版本身份断言闭包返工交付报告.md`
- `docs/agent/M3_G1_P0I_R2_交付报告行尾与验证真实性返工交付报告.md`

不得修改生产代码、测试、配置、600733 证据、P0I/P0I-R1 任务书或独立复验报告。

## 3. 必须完成

1. 删除 R1 交付报告第 5–6 行及全文件的 trailing whitespace。
2. 在 R1 交付报告中追加“R2 更正”：
   - 原提交 `66052b0` 的 `git --check` 自报为 0 是错误记录；
   - 独立复验实测为退出 2；
   - 本 R2 提交修正行尾后，从 `d090d1e` 到 R2 提交的白名单 diff check 必须为 0；
   - 不篡改 R1 当时的功能测试结果。
3. R2 交付报告准确记录命令、退出码、范围和未验证项；自身不得含 trailing whitespace。

## 4. 验收命令

```text
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_g1_planning.py::test_static_plan_from_c0_and_forged_identity tests/unit/test_m3_reference.py::test_p0e_reconciliation_version_propagates_in_build_spec -q
git diff --check d090d1e7dda1b315b51915b85d0f3f1fc3859bee -- docs/agent/M3_G1_P0I_R1_对账版本身份断言闭包返工交付报告.md docs/agent/M3_G1_P0I_R2_交付报告行尾与验证真实性返工交付报告.md
git show --check --oneline <R2提交>
```

上一轮 308 passed / 5 skipped 已由独立复验真实执行且代码未变，本轮不得机械重跑四文件长套件。

## 5. 独立复验

由另一全新 `cursor-grok-4.5-high` 会话承担，生产代码、测试和实现报告只读；唯一写入：

```text
docs/agent/M3_G1_P0I_R2_交付报告行尾与验证真实性独立复验报告.md
```

复验必须：

- 重跑 §4 三类检查；
- 逐行核对 R2 对原错误记录的更正是否准确；
- 检查实现提交仅含两份白名单报告；
- 明确 PASS/FAIL，不宣称主验或 Gate。

## 6. 通过条件

- 两份实现报告均无 trailing whitespace；
- R1 错误自报已显式、更正且保留审计历史；
- R2 diff/show check 均退出 0；
- 最小两测仍为 2 passed；
- 全新外部独立复验明确 PASS。
