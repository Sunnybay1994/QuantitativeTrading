# M3 G1 P0K-A-R2：五阶段最小 fixture 与中断恢复返工任务单

## 1. 状态与目标

P0K-A-R1 的外部实现已形成白名单内未提交差异，关键定向测试、Ruff 和 mypy 已取得通过证据；
但任务书全组 pytest 在
`tests/unit/test_m3_g1_workflow.py::test_five_stage_fake_publish_and_inspect_closure`
运行约 95 分钟时，Cursor 外部连接连续重试并以 `[resource_exhausted]` 退出，pytest 子进程随会话被回收，
因此该次全组运行没有最终结论。

本轮目标是：

1. 接管并逐项复核现有未提交差异，不假设其天然完整；
2. 保留五阶段闭环的全部生产路径与断言，将该单元测试缩为最小且确定的 30 证券 fixture；
3. 清理首轮会话遗留的根目录 `_p0ka_*.py` 临时脚本；
4. 完成 R1 原合同、定向验证、交付报告和单一提交。

## 2. 现象—根因—应遵循规则

### 2.1 现象

- 全组 pytest 已完成前 196 个节点，无失败；
- 第 197 个节点为五阶段闭环测试，使用 `_symbols()` 默认 300 证券；
- P0K-A 又为每个证券增加 `stock_dividend` 与 `stock_share_change` 两个独立 raw-first 请求；
- 测试持续约 95 分钟且工作集从约 0.2GB 增长至约 2.7GB；
- 最终 Cursor 外部连接报 `[resource_exhausted]`，没有 pytest exit summary。

### 2.2 根因

该测试把“验证真实五阶段控制流”与“CSI300 全规模 fixture”耦合。新增两条逐证券 CNINFO 链后，
单测成本随请求、journal、raw、candidate/release 重建显著放大。外部连接中断不是生产合同失败，
但暴露了单元测试违反最小 fixture 原则。

### 2.3 应遵循规则

- `AGENTS.md` §7：开发阶段默认使用最小、确定且覆盖边界的 fixture，不能用大范围数据代替单元/合同测试；
- 五阶段测试仍必须真实经过 INDEX → HISTORY → REFERENCE → PREPARE → PUBLISH → INSPECT；
- 不 mock 掉新增 CNINFO plan、journal、raw verification、candidate identity 或 release consume；
- CSI300 的 300 成分数量合同由已有专门测试继续覆盖，不要求此五阶段控制流测试重复承担全规模覆盖。

## 3. 冻结实现边界

### 3.1 允许修改

沿用 P0K-A 与 P0K-A-R1 的合并白名单；本轮新增报告路径：

- `docs/framework/agent/M3_G1_P0K-A-R2_五阶段最小fixture与中断恢复交付报告.md`

### 3.2 五阶段 fixture 修订

对 `test_five_stage_fake_publish_and_inspect_closure`：

- 使用现有 `_patch_resume_fixture_scale(...)` 或等价的测试内 monkeypatch，将本测试缩为 30 证券；
- `_CountingProClient` 与所有预期计划/候选输入必须使用同一 30 证券集合；
- 保留两条 CNINFO corporate-action batch 的真实规划、执行、journal 复用和 candidate/release 投影；
- 保留重复 HISTORY、重复 REFERENCE、unsupported publish、PREPARE、PUBLISH、最终 INSPECT 和零网络断言；
- 不降低生产默认 `_EXPECTED_COUNT=300`，不修改正式配置，不改变真实 G1 行为；
- 若现有 helper 的字面职责过窄，可最小重命名为通用的 workflow fixture 缩放 helper，并同步其调用方。

## 4. 禁止项

- 不进入 P0K-B，不把 CNINFO frame 选择进 ledger；
- 不跳过或 `xfail` 五阶段闭环测试；
- 不删除关键断言来换取速度；
- 不修改或暂存既有脏 `docs/agent/*.md`；
- 不提交 `_p0ka_*.py`、日志、raw、journal、缓存或其他临时产物；
- 不使用网络测试；
- 不以中断的 95 分钟 pytest 作为通过证据。

## 5. 最小复现与新增验证

先单独运行：

```powershell
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_g1_workflow.py::test_five_stage_fake_publish_and_inspect_closure -q --tb=short
```

通过条件：

- 单测通过；
- fixture 为 30 证券；
- 五阶段和两条新 CNINFO 链均实际执行；
- 运行时间显著低于中断前的 95 分钟，不发生外部连接资源耗尽。

随后运行 P0K-A-R1 任务书的完整定向 pytest、Ruff、mypy 和 `git diff --check`。若完整定向 pytest
仍有其他重型节点，应先报告精确节点和证据，不得无限等待或用中断结果宣称通过。

## 6. 交付

交付报告必须包含：

- 现有差异逐项复核结果；
- 五阶段 fixture 修改前后规模与耗时；
- R1/P0K-A 合同映射；
- 所有验证命令、通过/失败/跳过摘要；
- 已清理的临时文件；
- 仍存风险。

只暂存合并白名单文件与本轮交付报告，提交一次。实现 Agent 不宣布主 Gate 通过。
