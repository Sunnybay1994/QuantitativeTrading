# M3 G1 BENCH-B1B-R1：Workflow 基金 Fake 闭包外部独立复验报告

- 角色：外部独立复验 Agent（未参与实现的全新会话）
- 实际模型：`cursor-grok-4.5-high`
- 任务单：`docs/agent/M3_G1_BENCH-B1B-R1_Workflow基金Fake闭包返工任务单.md`
- 交付报告：`docs/agent/M3_G1_BENCH-B1B-R1_Workflow基金Fake闭包外部返工交付报告.md`
- 只读范围：生产代码、配置、实现者测试均未修改
- 唯一写入：本报告
- 复验结论：**R1 快速合同与对抗性反例通过（PASS）**；完整 HISTORY 长测仍属主 Agent 待验；**不得也不宣布 B1B / G1 Gate**

## 1. 范围与白名单核对

| 项 | 证据 | 结果 |
|---|---|---|
| R1 语义改动落在 `tests/unit/test_m3_g1_workflow.py` | `git diff -w --stat`：`+254 / -11`（忽略空白）；内容为 `_BENCHMARK=510300.SH`、三基金 fake、闭包断言、快速合同测试、bounded-resume 基金 identity 补强 | PASS |
| 交付报告存在 | `docs/agent/...外部返工交付报告.md` 为未跟踪新文件 | PASS |
| 本会话未改生产/配置/实现者测试 | 复验仅读；唯一写入本报告 | PASS |
| 工作区另有非 R1 脏文件 | `src/quant/data/*`、`g1_planning.py`、`configs/research/m3_qlib_example.toml` 等仍有修改（属既有并行工作区状态，非本复验改动） | 记录；不据此宣布 Gate |

## 2. 合同逐项映射

| 任务合同要求 | 实现证据 | 复验结果 |
|---|---|---|
| `_CountingProClient` 增加 `fund_daily/fund_adj/fund_div` | `tests/unit/test_m3_g1_workflow.py` 方法体；`fields`/`ts_code` 与 `TUSHARE_FIELDS` / `_BENCHMARK` 对齐 | PASS（代码审查） |
| `fund_daily` 独立 endpoint 计数 | `_count("fund_daily")` + `endpoint_calls` | PASS（快速测 + 对抗） |
| `fund_adj` 覆盖分段且 identity 可区分 | 两段不同 `start_date/end_date` → `adj_ids[0] != adj_ids[1]` | PASS |
| `fund_div` 非空、`div_proc=实施`、事件在 history 窗外 | `_fund_div_frame` 日期 `20100105` 等；窗口信号为 `2016-02-01` | PASS（代码审查 + 快速测） |
| 不空响应绕过 REJECT | `frame.height >= 1` | PASS |
| HISTORY 闭包：`fund_daily=1`、计划内 `fund_adj`、`fund_div=1`、`index_daily=0` | `_assert_history_fund_fake_closure`；接入 `test_five_stage...` 与 bounded resume | PASS（代码审查）；**长测运行待主 Agent** |
| bounded resume 不重复已完成基金 identity | 前缀稳定 + `len(set(...))==len(...)`；推进到首个基金请求后再跨 1 笔 | PASS（代码审查）；**长测运行待主 Agent** |
| 返回列与 `TUSHARE_FIELDS` 精确一致 | `_assert_exact_fields` + 快速合同列断言 | PASS |
| 不改生产、不联网、不发布 | 白名单与本会话约束 | PASS |
| 新增实现者未用的反例 | 见 §4（错误 fields/ts_code fail-closed） | PASS |

## 3. 命令与真实结果

### 3.1 Windows 快速合同测试

```text
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_g1_workflow.py::test_counting_pro_client_fund_endpoint_contract -q --tb=short
```

```text
.                                                                        [100%]
1 passed in 2.26s
PYTEST_EXIT=0
```

**结果：PASS**

### 3.2 Ruff 定向检查

```text
D:\Miniforge3\python.exe -m ruff check tests/unit/test_m3_g1_workflow.py
```

```text
All checks passed!
RUFF_EXIT=0
```

**结果：PASS**

### 3.3 `git diff --check`

Windows 本机 `git.exe` 不可用（PATH 指向 `C:\Program Files\Git\...` 但可执行文件缺失）。改用 WSL 同源树执行（只读）：

```text
wsl -e bash -lc 'cd /home/mabw/AI_Coding_win/QuantitativeTrading && git diff --check -- tests/unit/test_m3_g1_workflow.py "docs/agent/M3_G1_BENCH-B1B-R1_Workflow基金Fake闭包外部返工交付报告.md"; echo DIFF_CHECK_EXIT=$?'
```

```text
DIFF_CHECK_EXIT=0
```

另对本机文件做 trailing-whitespace / conflict-marker 扫描：**PASS**。

**结果：PASS**（经 WSL `git diff --check`）

### 3.4 未运行（按合同禁止本复验启动）

```bash
python -m pytest \
  tests/unit/test_m3_g1_workflow.py::test_five_stage_fake_publish_and_inspect_closure \
  tests/unit/test_m3_g1_workflow.py::test_history_bounded_incomplete_then_resume_success -q
```

**状态：未执行；长测仍属主 Agent 待验。不得据此关闭 B1B。**

## 4. 实现者未使用的只读对抗性反例

实现者快速测只覆盖合法参数与正向计数。本复验用 `D:\Miniforge3\python.exe -c`（不写仓库临时文件）额外证明：

1. 分别对 `fund_daily` / `fund_adj` / `fund_div` 传入错误 `fields` 或错误 `ts_code` → 均 `AssertionError`（fail closed）；
2. 失败请求**不**增加 `endpoint_calls` / `fund_request_identities`（断言位于 `_record_fund_identity` / `_count` 之前）；
3. 合法两段 `fund_adj` identity 唯一；
4. 仅调用基金端点后 `index_daily=0`；
5. 正向成功后再喂错误 `fields`，计数与 identity 仍不增长。

真实输出摘要：

```text
ADVERSARIAL_OK
PASS fail-closed fund_daily ...
PASS fail-closed fund_adj ...
PASS fail-closed fund_div ...
PASS distinct fund_adj segment identities
PASS index_daily=0 after fund calls only
PASS post-success bad fields do not increment counters
endpoint_calls {'fund_daily': 1, 'fund_adj': 2, 'fund_div': 1}
n_identities 4 unique 4
```

**结果：PASS**

## 5. 总表与交接

| 检查项 | 结果 |
|---|---|
| 快速合同 pytest | PASS |
| Ruff | PASS |
| `git diff --check` | PASS |
| 对抗性 fail-closed + identity/`index_daily` | PASS |
| 五项合同语义（代码映射） | PASS |
| HISTORY 完整长测两条 | **未跑 / 主 Agent 待验** |
| B1B / G1 Gate | **不宣布** |

### 给主 Agent

1. R1 外部独立复验（快速路径 + 对抗反例）通过，可吸收本报告进入主验。
2. 主验仍须实际跑任务书两条 HISTORY 长测，并继续 B1B 其余分组回归。
3. 工作区尚有其他非 R1 修改文件；合流时勿把它们误记为 R1 白名单产物。
4. 本报告**不**构成 B1B 或 G1 Gate 关闭证据。
