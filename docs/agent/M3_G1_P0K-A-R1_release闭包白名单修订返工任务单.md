# M3 G1 P0K-A-R1：release 闭包白名单修订返工任务单

状态：**冻结，待全新外部实现**

日期：2026-07-29（Asia/Shanghai）

上游任务：
[`M3_G1_P0K-A_CNINFO股改分红与股本变动raw-first全链任务单.md`](M3_G1_P0K-A_CNINFO股改分红与股本变动raw-first全链任务单.md)

停止报告：
[`M3_G1_P0K-A_CNINFO股改分红与股本变动raw-first全链交付报告.md`](M3_G1_P0K-A_CNINFO股改分红与股本变动raw-first全链交付报告.md)

返工基线：`64d296e2db3279e3bd4b94d2e283e8c8c3b82ee3`

## 1. 现象

首轮外部实现未改代码并正确停止。上游任务要求 `G1BuildInputs` 新增：

```text
cninfo_dividend_responses
cninfo_share_change_responses
```

但白名单漏了 `src/quant/data/m3_release.py`；该模块 `_consume_build_inputs` 显式逐字段重建
`G1BuildInputs`。上游白名单还列出不存在的 `tests/unit/test_m3_backfill.py`，实际 SSOT 测试文件为
`tests/unit/test_m3_backfill_requests.py`。

## 2. 根因

主 Agent 冻结任务时只沿 candidate/workflow/reference 调用链检查 identity，没有闭包到 release
反序列化入口和直接构造 `G1BuildInputs` 的测试。被破坏的不变量是：

> 公共冻结 dataclass 增加必需字段时，所有显式重建、反序列化、release 入口和直接构造测试必须在同一
> 变更中闭包；文件白名单必须覆盖完整调用链。

## 3. 最小复现

```text
src/quant/data/m3_release.py::_consume_build_inputs
  -> G1BuildInputs(...)
  -> 当前只传旧字段

tests/unit/test_m3_g1_release.py
  -> 两处显式 G1BuildInputs(...)

tests/unit/test_m3_backfill_requests.py
  -> 硬编码 m3-g1-request-plan-v2 和三参数 _plan_hash(...)
```

若只按上游白名单修改 candidate/plan，release 构造会缺字段，plan v2 测试也会失配。

## 4. 修订后的白名单

上游任务所有合同继续有效。其 §8 白名单作以下唯一修订：

删除不存在的：

```text
tests/unit/test_m3_backfill.py
```

增加：

```text
src/quant/data/m3_release.py
tests/unit/test_m3_g1_release.py
tests/unit/test_m3_backfill_requests.py
docs/agent/M3_G1_P0K-A-R1_release闭包白名单修订返工交付报告.md
```

首轮停止报告保持历史不可变，不得覆盖。其余白名单和禁止项不变。

## 5. 新增测试要求

除上游 §9 外，必须增加：

1. release `_consume_build_inputs` 对两个新 tuple 精确重建；
2. 任一新 tuple 的 spec/receipt/frame 篡改在 release 入口 fail closed；
3. plan v3 hash 包含五个 batch，交换/遗漏新 batch 改变或拒绝 identity；
4. 旧 plan v2 不能通过新 plan 构造；
5. PREPARE/PUBLISH 相关 build inputs fixture 不丢失新 receipt projection；
6. 所有直接 `G1BuildInputs(...)` fixture 显式提供两个新 tuple，不用危险默认值掩盖缺口。

## 6. 通过条件

Windows 原生：

```text
D:\Miniforge3\python.exe -m pytest \
  tests/unit/test_cninfo_connector.py \
  tests/unit/test_m3_backfill_requests.py \
  tests/unit/test_m3_g1_planning.py \
  tests/unit/test_m3_g1_workflow.py \
  tests/unit/test_m3_g1_candidate.py \
  tests/unit/test_m3_g1_release.py \
  tests/unit/test_m3_reference.py \
  tests/unit/test_m3_run_g1.py -q
```

另运行白名单源码/测试定向 Ruff、白名单源码 mypy、实现基线到交付 commit 的白名单
`git diff --check`。

实现仍保持零网络，不运行正式 1274 请求，不读取 token，不处理 P0K-B。全新外部实现 Agent 只提交
修订后白名单；完成后必须由另一全新外部 Agent 独立初验。
