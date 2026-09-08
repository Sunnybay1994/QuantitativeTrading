# M3 G1 P0I-R1：对账版本身份断言闭包独立复验报告

状态：**FAIL**（不等于主验 / G1 Gate / REFERENCE / PREPARE / PUBLISH / Linux Gate）

日期：2026-07-29（Asia/Shanghai）
审查对象：实现提交 `66052b05c91ed2c9e02f9bc80bc4eb9ad723772a`（相对任务冻结 `cb8dae820c491069e6cd07ee5de0f0d1cea514d5`；上游初验 FAIL `e8e1cbbb55df28dd3e717e01b1f551f09b20a59c`）
审查模型：`cursor-grok-4.5-high`（外部独立复验全新会话；非实现者）
角色：生产代码 / 配置 / 实现者测试 / 实现交付报告全部只读；唯一仓库写入为本报告

冻结合同：
- [`M3_G1_P0I_R1_对账版本身份断言闭包返工任务单.md`](M3_G1_P0I_R1_对账版本身份断言闭包返工任务单.md)
- 实现交付：[`M3_G1_P0I_R1_对账版本身份断言闭包返工交付报告.md`](M3_G1_P0I_R1_对账版本身份断言闭包返工交付报告.md)

## 1. 审查范围与方法

- 只读核对 `66052b0` 四路径白名单 diff 与交付报告全文
- 独立重跑任务书验收命令 + 复验四文件长套件 + ruff + `rg` + `git diff --check cb8dae8` + `git show --check 66052b0`
- 专项核查主 Agent 观察：交付报告第 5–6 行尾空白 vs 自报 `diff --check` 通过
- 增加实现者未使用的对抗性身份探针（跨模块 SSOT 同一对象 + 陈旧 v5 BuildSpec 拒绝）
- 零网络、无凭据、不碰正式 `data/`、不改生产/测试

## 2. 合同逐项证据表

| 合同项 | 独立证据 | 结论 |
|---|---|---|
| planning 断言绑定 `G1_CORPORATE_ACTION_RECONCILIATION_VERSION` 且精确为 v6 | `test_m3_g1_planning.py` L584–590：先钉 SSOT==`…_v6`，再钉 `plan.build_spec… ==` 常量；import 自 `m3_execution_facts` | 通过 |
| reference fixture/断言改为 v6（优先 SSOT；显式串值同时钉常量） | `test_p0e_reconciliation_version_propagates_in_build_spec`：常量==v6，且 `spec… ==` 常量；`_build_spec()` 已用常量 | 通过 |
| 测试树无旧 v5 当前 recon 期望 | `rg -n "tushare_factor_daily_preclose_v5" tests/unit` → 无命中，退出码 1 | 通过 |
| 600733 证据文档撤回过早“初验已通过”；不证明 P0I/Gate；数值证据未改 | 文首改为“P0I-R1 尚待独立复验…**不证明** P0I/Gate”；`rg` 无“独立初验已通过”；表格数值与处置边界保留 | 通过 |
| 不改生产代码 / 配置 / 正式 data / 延迟闭包 / 600733 处置 | `66052b0` 仅 4 白名单路径；`git diff e8e1cbb 66052b0 -- src/ configs/` 空 | 通过 |
| 两个最小复现测试转绿 | Windows `D:\Miniforge3\python.exe`：2 passed，退出码 0 | 通过 |
| 四文件长套件 | 同解释器：`308 passed, 5 skipped`，退出码 0（约 29m57s） | 通过 |
| ruff 白名单两测 | `ruff check tests/unit/test_m3_g1_planning.py tests/unit/test_m3_reference.py` → All checks passed，退出码 0 | 通过 |
| 提交白名单卫生 | `git show --name-only 66052b0` 仅任务书白名单四路径 | 通过 |
| `git diff --check` / `git show --check` | 见 §3：**失败**；交付报告却自报退出码 0 | **失败** |
| 对抗性身份探针（实现者未用） | 见 §4：跨模块同一对象 + 拒收陈旧 v5 → PASS | 通过（探针本身） |

## 3. 专项：交付报告尾空白 vs 自报 diff-check 通过

### 现象

- 交付报告 §3 表写明：`git diff --check e8e1cbb… -- <白名单>` → **退出码 0**。
- 独立复验对同一实现提交重放：
  - `git show --check 66052b05c91ed2c9e02f9bc80bc4eb9ad723772a` → **退出码 2**
  - `git diff --check cb8dae820c491069e6cd07ee5de0f0d1cea514d5 -- <白名单四路径>` → **退出码 2**
  - `git diff --check e8e1cbbb55df28dd3e717e01b1f551f09b20a59c -- <白名单四路径>` → **退出码 2**
- 三处均报：

```text
docs/framework/agent/M3_G1_P0I_R1_对账版本身份断言闭包返工交付报告.md:5: trailing whitespace.
docs/framework/agent/M3_G1_P0I_R1_对账版本身份断言闭包返工交付报告.md:6: trailing whitespace.
```

- 工作区字节核验：第 5、6 行末尾各有两个 ASCII space（`0x20 0x20`，Markdown soft-break 风格），确认为 trailing whitespace。
- 同提交内 600733 证据文档反而**去掉**了同类行尾空格，说明实现者知悉 `--check` 语义，却在交付报告中引入并误报通过。

### 根因

交付报告新增文件在元数据行使用行尾双空格；未（或未对白名单含本报告路径）通过 `git diff --check` / `git show --check`，却在交付证据表中记录退出码 0。身份钉同步本身未因此回退，但这是**提交卫生与交付证据失真**，违反任务书静态检查通过条件。

### 应遵循规则

- 任务书 §5/§6：白名单与静态检查（含 `git diff --check`）必须真实通过；
- AGENTS.md / 多 Agent 闭环：实现自测证据不得与可复现命令结果冲突；独立复验必须映射证据，不得采信自报；
- 文档行尾 Markdown soft-break 不得伪装成 `--check` 已绿。

### 最小复现

```text
git show --check 66052b05c91ed2c9e02f9bc80bc4eb9ad723772a
git diff --check cb8dae820c491069e6cd07ee5de0f0d1cea514d5 -- docs/framework/agent/M3_G1_P0I_R1_对账版本身份断言闭包返工交付报告.md docs/framework/agent/20260729_P0I后正式status首败_600733有事件declared不合.md tests/unit/test_m3_g1_planning.py tests/unit/test_m3_reference.py
```

期望当前均非零退出，并指出交付报告 L5/L6 trailing whitespace。

### 新增测试 / 必跑检查

返工后必须重跑上述两条 `--check`（以及任务书原 `e8e1cbb` 基线 `--check`），退出码均为 0；交付报告不得再出现与命令结果矛盾的自报。

### 通过条件

- 白名单路径（含交付报告）对 `git show --check <实现提交>` 与 `git diff --check <冻结基线>` 均为退出码 0；
- 交付证据表与独立重放一致；
- 身份钉合同项保持本报告 §2 已通过状态；再由全新外部独立复验重开本文件结论。

## 4. 实现者未使用的对抗性身份探针

环境：Windows `D:\Miniforge3\python.exe`；`PYTHONPATH=src;.`；零网络。实现者仅钉常量==v6、`build_spec` 传播，以及 `replace(..., v3)` 拒绝；**未**覆盖陈旧 v5 拒收与跨模块同一对象。

| # | 反例 | 结果 |
|---|---|---|
| ADV-1 | `m3_execution_facts` / `m3_g1_candidate` / `g1_planning` 三处 `G1_CORPORATE_ACTION_RECONCILIATION_VERSION` 必须均为 `…_v6` 且 `is` 同一对象 | PASS |
| ADV-1 | `replace(合法 G1BuildSpec, corporate_action_reconciliation_version="tushare_factor_daily_preclose_v5")` 必须 `ValueError` 且信息含该字段名 | PASS（`ADV_STALE_V5_REJECT`） |

探针退出码 0。该探针不拯救 §3 的 `--check` FAIL。

## 5. 定向验证命令与退出码

解释器：`D:\Miniforge3\python.exe`（Windows 原生反馈环）。

| 命令 | 退出码 |
|---|---|
| `pytest …::test_static_plan_from_c0_and_forged_identity …::test_p0e_reconciliation_version_propagates_in_build_spec -q` | **0**（2 passed） |
| `pytest tests/unit/test_m3_execution_facts.py tests/unit/test_m3_g1_candidate.py tests/unit/test_m3_g1_planning.py tests/unit/test_m3_reference.py -q` | **0**（308 passed, 5 skipped，~1797s） |
| `ruff check tests/unit/test_m3_g1_planning.py tests/unit/test_m3_reference.py` | **0** |
| `rg -n "tushare_factor_daily_preclose_v5" tests/unit` | **1**（无命中） |
| ADV-1 跨模块 + 陈旧 v5 拒收探针 | **0** |
| `git diff --check cb8dae8… -- <白名单>` | **2**（交付报告 L5/L6 trailing whitespace） |
| `git show --check 66052b0` | **2**（同上） |
| `git diff --check e8e1cbb… -- <白名单>`（任务书原命令复核） | **2**（同上） |

## 6. 明确未运行 / 不宣称

- 正式网络、凭据、status/HISTORY/REFERENCE/PREPARE/PUBLISH
- 全量 pytest / 全量 Ruff/mypy
- WSL Miniforge base Gate / Linux 平台终验
- Codex / 主 Agent 终验
- **不宣称** P0I / P0I-R1 / G1 Gate 通过

## 7. 返工项（唯一阻断）

| 字段 | 内容 |
|---|---|
| 现象 | 交付报告 L5/L6 行尾空白；`git show --check` / `git diff --check` 退出码 2；交付却自报 0 |
| 根因 | 新增交付报告引入 trailing whitespace，且静态检查证据失真 |
| 应遵循规则 | 任务书白名单静态检查真实通过；交付证据可独立复现 |
| 最小复现 | §3 两条 `--check` 命令 |
| 新增测试/检查 | 返工后 `--check` 必须为 0；禁止矛盾自报 |
| 通过条件 | `--check` 全绿 + 身份钉合同保持 §2 已通过项 + 全新外部独立复验重开 |

身份钉同步与四文件绿测**不**构成整体 PASS；在提交卫生修复并经复验前，不得进入主 Agent 终验。

## 8. 最终结论

**FAIL**

阻断项：实现提交交付报告尾空白导致 `git --check` 失败，且与交付自报冲突。其余身份闭包合同项与定向绿测见 §2/§5，仅作返工后复验基线，不升格为本轮通过。
