# M3 HISTORY-H4 有界恢复执行任务单

## 1. 目标

当前 `history` 会恢复已有 receipt，但一次调用仍会尝试所有缺失请求，不能按额度或运行窗口主动停下。新增
**按新提交 request identity 计数**的有界执行能力，使真实 HISTORY 可分批恢复；本任务只实现零网络代码和
测试，不授权任何真实数据请求。

## 2. 冻结语义

1. CLI `history` 新增可选 `--max-new-requests N`。`N` 必须是严格正整数；未提供时保持原全阶段语义。
2. 上限只统计本次调用从“无有效 receipt”推进到“成功提交 receipt”的 request identity；恢复已有 receipt
   不占额度，单个 identity 内的 retry attempt 不改变该计数。
3. 到达上限后不得为下一缺失 identity 新建/改写 intent、candidate、receipt 或 raw；已有 receipt 仍可只读
   恢复验证。禁止通过提前退出绕过调用前的全局 journal/static preflight。
4. 有界调用若尚未完成 HISTORY，应返回最新 verified workflow state，CLI 输出 `outcome=INCOMPLETE`、退出码
   `0`；若恰好完成则 `SUCCESS`、退出码 `0`。非法输入或执行失败沿用现有稳定错误协议及非零退出码。
5. 未提供上限时，`run_g1_history_stage` 未完成仍按既有 `G1_WORKFLOW_HISTORY_INCOMPLETE` fail-closed。
6. 不能伪造 `HISTORY` completed stage，不能更改 request/receipt/raw identity、计划顺序、5000 门禁、重试策略
   或其他 stage 行为。
7. CLI JSON 增加本轮 `max_new_requests` 与 `new_requests_committed`（严格整数或 null），字段进入严格值对象验证；
   status/其他命令分别为 null/0，不得猜测累计 API attempt。

## 3. 文件白名单

- `src/quant/data/m3_backfill.py`
- `src/quant/research/m3/g1_workflow.py`
- `src/quant/research/m3/run_g1.py`
- `tests/unit/test_m3_backfill_requests.py`
- `tests/unit/test_m3_g1_workflow.py`
- `tests/unit/test_m3_run_g1.py`
- `README.md`（仅同步 CLI 用法）
- `docs/framework/agent/M3_HISTORY-H4有界恢复执行交付报告.md`

若严格 JSON 结果合同需要修改白名单外公共 contract，停止并报告，不得越权。

## 4. 必测反例

- `N=True/0/-1/1.0/"1"` 在任何 FS/API 副作用前拒绝；
- 有 114 个已完成 receipt、`N=2` 时只新增两个 identity，不把 114 计入额度；
- 达上限后的下一缺失 identity 零 journal/raw 增量；
- 第二次 `N=2` 从前次断点再新增两个，而非重复请求；
- 单 identity 首次可重试失败、第二次成功，只计一个 committed identity；永久失败不计 committed 且仍失败；
- 有界调用完成最后不足 N 个请求时返回 SUCCESS；未完成返回 INCOMPLETE 且 completed stages 仍仅含 INDEX；
- 无上限既有 happy/failure 行为不变；status 与其他命令不触发网络。

自动测试必须用最小 fake/fixture，不读取项目真实 data，不运行真实 status/history。

## 5. 定向验证

WSL Miniforge base：

```bash
python -m pytest tests/unit/test_m3_backfill_requests.py -q -k 'bounded or max_new or resume'
python -m pytest tests/unit/test_m3_g1_workflow.py -q -k 'history and not five_stage'
python -m pytest tests/unit/test_m3_run_g1.py -q -k 'history or max_new'
ruff check src/quant/data/m3_backfill.py src/quant/research/m3/g1_workflow.py src/quant/research/m3/run_g1.py tests/unit/test_m3_backfill_requests.py tests/unit/test_m3_g1_workflow.py tests/unit/test_m3_run_g1.py
mypy src/quant/data/m3_backfill.py src/quant/research/m3/g1_workflow.py src/quant/research/m3/run_g1.py
```

禁止全量 pytest、five-stage、网络、项目真实 data 改写和 Git 初始化。实现与独立初验使用不同全新
`cursor-grok-4.5-high` 会话；初验除唯一报告外代码只读，并增加未公开的“预算到达后非法尾部 journal 仍须
被 preflight 拒绝”反例。
