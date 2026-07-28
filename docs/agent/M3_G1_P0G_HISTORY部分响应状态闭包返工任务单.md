# M3 G1 P0G：HISTORY 部分响应状态闭包返工任务单

状态：**冻结，待外部实现 → 外部独立初验**

日期：2026-07-28（Asia/Shanghai）  
实现基线：`28d19a8`（Accept G1 P0F CNINFO rights closure）

## 1. 正式复现

Windows 原生正式命令：

```text
D:\Miniforge3\python.exe -m quant.research.m3.run_g1 --config configs/research/m3_qlib_example.toml status
```

结果：

- 运行约 386 秒；
- 零网络；
- CLI 返回 `CLI_INTERNAL_ERROR`，exit 1。

直接调用同一 `inspect_g1_workflow` 的 traceback：

```text
ValueError: workflow state HISTORY 未完成产物闭包非法
```

正式磁盘状态为：INDEX 与旧 Tushare HISTORY receipts 完整，但新 CNINFO HISTORY receipts 尚不存在。

## 2. 现象—根因—规则—最小复现—新增测试—通过条件

### P0G-1：HISTORY incomplete 泄漏部分 Tushare responses

- **现象**：Tushare history 完整、CNINFO history 不完整时，`_inspect` 已把 Tushare responses 写入最终 state，但 `completed_stages` 只有 `("INDEX",)`；状态对象自证失败，CLI 压缩为 `CLI_INTERNAL_ERROR`。
- **根因**：`history_responses` 在确认 CNINFO batch complete 之前赋值；HISTORY 未完成分支要求它为空。
- **规则**：stage 未完成时不得暴露该 stage 的部分产物；部分 raw/journal 可以留在磁盘恢复，但 verified workflow state 必须只暴露完成阶段的闭包。
- **最小复现**：INDEX complete + Tushare history complete + CNINFO batch missing/partial，调用真实 `_inspect`。
- **新增测试**：
  - `status` / `inspect` 返回成功的 INCOMPLETE state；
  - `completed_stages == ("INDEX",)`；
  - `history_responses == ()`、`cninfo_responses == ()`、`candidate is None`、reference/prepared/published 为空；
  - counts 仍描述完整计划 totals，不改变既有含义；
  - socket/connector 被阻断时仍零网络、零写。
- **通过条件**：正式 `status` exit 0、outcome INCOMPLETE，不再 `CLI_INTERNAL_ERROR`。

### P0G-2：状态闭包遗漏 CNINFO response IDs

- **现象**：`_validate_workflow_state_closure` 在 INDEX/HISTORY incomplete 分支未检查 `cninfo_responses`；HISTORY complete 分支只核对 Tushare response IDs。
- **根因**：P0F 新增 state 字段后，闭包验证未同步覆盖所有生命周期分支。
- **规则**：HISTORY 是 Tushare + CNINFO 两个独立 source 的联合完成条件；state 必须绑定两批精确有序 request IDs。
- **最小复现**：
  - 对 fresh/index-only state 注入任意 verified CNINFO response；
  - 对 HISTORY-complete state 删除、重排或替换 CNINFO response。
- **新增测试**：上述所有篡改均在 dataclass/state closure 边界稳定拒绝。
- **通过条件**：
  - INDEX 未完成与 HISTORY 未完成均强制 `cninfo_responses == ()`；
  - HISTORY 完成必须精确满足 `derived.request_plan.cninfo_rights_batch.requests` 的有序 IDs；
  - candidate 与后续阶段既有闭包不回退。

## 3. 冻结实现

- `_inspect` 使用局部 verified Tushare history 值；只有 Tushare 与 CNINFO 两批都 complete 且验证成功后，才一次性赋给最终 `history_responses` / `cninfo_responses` 并构建 candidate。
- 不允许通过放宽 `VerifiedG1WorkflowStateV1` incomplete 规则来容纳部分响应。
- `_validate_workflow_state_closure`：
  - INDEX 未完成：增加 `cninfo_responses == ()`；
  - HISTORY 未完成：增加 `cninfo_responses == ()`；
  - HISTORY 完成：核对 CNINFO expected/actual request IDs 的精确有序 tuple。
- 不删除、移动或改写现有 raw/journal；恢复语义不变。
- 不改变 HISTORY counts、CLI JSON Schema、错误码、版本常量、candidate/release 身份或 CNINFO connector。
- 这是内部状态闭包修复，不做版本 bump；source tree hash 自然变化，旧 candidate/reference/prepare/publish 仍不得复用。

## 4. 文件白名单

生产：

- `src/quant/research/m3/g1_workflow.py`

测试：

- `tests/unit/test_m3_g1_workflow.py`
- `tests/unit/test_m3_run_g1.py`

文档：

- 唯一新交付报告：`docs/agent/M3_G1_P0G_HISTORY部分响应状态闭包返工交付报告.md`

如必须修改其他生产文件，停止扩大并报告证据。

## 5. 必须验证

1. Tushare complete + CNINFO missing；
2. Tushare complete + CNINFO partial；
3. 两批 complete 后 HISTORY 正常完成；
4. fresh/index/history state 的 CNINFO response 注入、缺失、重排、替换反例；
5. `status` 零网络、零写、exit 0 INCOMPLETE；
6. `history --max-new-requests` 既有 bounded resume 不回退；
7. workflow 与 CLI 定向 Ruff、mypy；
8. `git diff --check 28d19a8 HEAD`。

只运行最小确定 fixture；不得机械重跑已知超慢 five-stage/candidate/release 全文件。

## 6. 交付边界

外部实现提交白名单代码、测试和唯一交付报告。另一全新外部会话必须独立重放正式形状反例并 PASS，之后由主 Agent 重跑 Windows/WSL status。P0G 通过前禁止正式 CNINFO 网络 HISTORY。

