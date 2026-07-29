# M3 G1 P0I-R1：对账版本身份断言闭包返工任务单

状态：**设计已冻结，待外部实现 → 外部独立复验 → 主 Agent 终验**

日期：2026-07-29（Asia/Shanghai）

## 1. 现象与根因

P0I 实现提交 `e2a3afbeb40a934ebdd6cf4749791b7d47749bbd` 已将
`G1_CORPORATE_ACTION_RECONCILIATION_VERSION` 升级为：

```text
tushare_factor_daily_preclose_suspension_resume_v6
```

外部独立初验提交 `e8e1cbbb55df28dd3e717e01b1f551f09b20a59c` 判定 FAIL：

- `tests/unit/test_m3_g1_planning.py` 仍断言旧 `tushare_factor_daily_preclose_v5`；
- `tests/unit/test_m3_reference.py` 仍构造并断言旧 `tushare_factor_daily_preclose_v5`；
- 生产 planning 已 import SSOT 常量并实际传播 v6，因此这是测试身份钉未同步，不是生产传播缺陷；
- `docs/agent/20260729_P0I后正式status首败_600733有事件declared不合.md` 又过早写成
  “P0I 独立初验已通过”，与权威 FAIL 报告冲突。

## 2. 应遵循规则

- 对账时点语义变化必须使用 v6，并自然传播到 planning、candidate、REFERENCE 和 release 身份；
- 测试不得另写与 SSOT 漂移的旧版本事实；
- P0I 初验通过只能由返工后的全新外部独立复验和主验共同证明；
- 600733 是 P0I 实现后的下一正式首败证据，但不属于本轮身份同步实现范围；
- 不改生产代码，不重新设计 P0I 延迟闭包，不处理 600733。

## 3. 实现白名单

外部实现 Agent 只可修改：

- `tests/unit/test_m3_g1_planning.py`
- `tests/unit/test_m3_reference.py`
- `docs/agent/20260729_P0I后正式status首败_600733有事件declared不合.md`
- `docs/agent/M3_G1_P0I_R1_对账版本身份断言闭包返工交付报告.md`

禁止修改生产代码、配置、正式 `data/`、既有 P0I 任务书/交付/初验报告和路线图。

## 4. 最小实现

1. planning 断言必须绑定
   `G1_CORPORATE_ACTION_RECONCILIATION_VERSION`，并证明值为
   `tushare_factor_daily_preclose_suspension_resume_v6`；不得复制旧 v5。
2. reference fixture/断言改为 v6，优先 import SSOT 常量；若该测试必须显式验证串值，同时断言常量精确为 v6。
3. `rg` 后测试树中不得残留 `tushare_factor_daily_preclose_v5` 作为当前 recon 身份期望。
4. 600733 证据文档的过早声明改为：P0I v6 实现后的正式探针已运行，但 P0I-R1 身份闭包尚待复验；该文档不证明 P0I/Gate 通过。
5. 不改变 600733 的数值证据、正式命令结果或后续处置边界。

## 5. 验收命令

Windows 原生：

```text
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_g1_planning.py::test_static_plan_from_c0_and_forged_identity tests/unit/test_m3_reference.py::test_p0e_reconciliation_version_propagates_in_build_spec -q
D:\Miniforge3\python.exe -m ruff check tests/unit/test_m3_g1_planning.py tests/unit/test_m3_reference.py
rg -n "tushare_factor_daily_preclose_v5" tests/unit
git diff --check e8e1cbbb55df28dd3e717e01b1f551f09b20a59c -- <白名单>
```

`rg` 允许历史任务书/报告记载旧值，不允许当前测试身份断言仍期待 v5。

外部独立复验必须由另一全新 `cursor-grok-4.5-high` 会话承担，只能写自己的唯一复验报告：

```text
docs/agent/M3_G1_P0I_R1_对账版本身份断言闭包独立复验报告.md
```

复验除上述最小两测外，还须运行：

```text
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_execution_facts.py tests/unit/test_m3_g1_candidate.py tests/unit/test_m3_g1_planning.py tests/unit/test_m3_reference.py -q
```

若长套件有明确已知耗时，按项目低频观察规则等待终态；不得用早期局部绿测代替最终结果。

## 6. 通过条件

- planning/reference 的当前身份断言统一绑定 v6 SSOT；
- 两个最小复现测试转绿；
- 测试树无旧 v5 当前 recon 期望；
- 600733 证据文档不再过早宣称 P0I 已通过；
- 白名单与静态检查通过；
- 全新外部独立复验明确 PASS 后，才进入主 Agent 的 Windows/WSL 与正式零网络终验。
