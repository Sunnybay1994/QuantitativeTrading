# M3 G1 BENCH-B1B-R0：超时部分实现恢复任务单

## 1. 现象

B1B 首个外部实现会话运行超过 30 分钟，shell wrapper 超时后 Cursor Node 子进程继续存活；主 Agent 又等待约
六分钟，确认最近十分钟无文件写入、CPU 几乎不增长且交付报告不存在后，精确终止该孤立进程。没有删除或
回滚任何部分改动。

当前审计事实：

- B1B 白名单内生产/测试已有较大部分实现，但没有外部交付报告；
- Windows 写过的多个 B1B 文件被整文件转换为 CRLF，WSL `git diff --check` 产生大量 trailing whitespace；
- WSL B1B 定向 pytest 在 `--maxfail=20` 下先通过 244 项，随后因
  `tests/unit/test_m3_reference.py::_build_inputs` 调用未导入的 `plan_history_requests`，产生 20 个 release
  fixture setup errors 后停止；完整剩余失败集尚未知；
- 真实网络、正式 raw/journal/receipt 和 release publish 均未执行。

## 2. 根因与应遵循规则

- 超时根因只能确定为首轮实现范围大且未在 30 分钟内完成/交付；不得猜测为代码已经完成。
- `NameError` 根因是测试 helper 的调用与导入在切换到新 ETF planner 时未同步，属于不完整重基线。
- whitespace 根因与 B1A-R1 相同：Windows 会话把既有 LF 文件写成 CRLF。

应遵循：从现有部分实现继续，小步修复第一个可复现失败并运行下一轮测试；所有 B1B 白名单文本最终保持 LF；
旧 v1 读取、新 v2 发布、3185 个证券 identity 不变、五个基金响应闭包等原 B1B 合同不得因赶进度弱化。

## 3. 最小复现

```bash
cd /home/mabw/AI_Coding_win/QuantitativeTrading
git diff --check
python -m pytest tests/unit/test_m3_g1_release.py -q --maxfail=1
```

返工前分别显示 CRLF trailing whitespace 与 `NameError: plan_history_requests is not defined`。

## 4. 续作范围

生产、配置与测试白名单完全继承原 B1B：

- `src/quant/data/__init__.py`
- `src/quant/data/m3_g1_candidate.py`
- `src/quant/data/m3_mappers.py`
- `src/quant/data/m3_release.py`
- `src/quant/research/m3/config.py`
- `src/quant/research/m3/g1_planning.py`
- `src/quant/research/m3/readiness.py`
- `configs/research/m3_qlib_example.toml`
- `tests/unit/test_m3_backfill_requests.py`
- `tests/unit/test_m3_contracts.py`
- `tests/unit/test_m3_g1_candidate.py`
- `tests/unit/test_m3_g1_mappers.py`
- `tests/unit/test_m3_g1_planning.py`
- `tests/unit/test_m3_g1_release.py`
- `tests/unit/test_m3_g1_workflow.py`
- `tests/unit/test_m3_golden_fixtures.py`
- `tests/unit/test_m3_labels.py`
- `tests/unit/test_m3_readiness.py`
- `tests/unit/test_m3_reference.py`

唯一报告：

- `docs/agent/M3_G1_BENCH-B1B_510300总回报映射与全链身份重基线外部实现交付报告.md`

除上述文件外只读。不得修改 B1A 任务/报告、路线图和交接，不得真实调用 Tushare，不得写正式数据或发布。

## 5. 必须完成的恢复动作

1. 先审阅现有部分 diff，不重置、不重新生成无关文件；
2. 把所有被本轮写成 CRLF 的白名单文本恢复为 LF，不改变可见字符；
3. 修复 `test_m3_reference` planner import/call 不一致，并执行 release 单文件收集/首错测试；
4. 逐轮修复后续真实失败，直到原 B1B §5 全部反例和 §6 验收集通过；
5. 对照原任务书逐项确认现有部分实现是否真的满足合同，不得以测试通过替代 3190 闭包、分红事件去重、
   因子对账、snapshot hash、v1/v2 exact-field 和 identity 传播审计；
6. 写压缩交付报告，明确继承部分实现、实际修复、测试结果和任何未决风险。

## 6. 新增回归检查与通过条件

本次不为缺失测试导入增加重复业务单测；新增结构回归 Gate 为：

```bash
python -m pytest tests/unit/test_m3_g1_release.py --collect-only -q
git diff --check
```

二者必须先通过，再运行原 B1B 完整定向 pytest、Ruff 和 mypy。所有 B1B 白名单 Python/TOML 文件必须
`CRLF=0`、bare CR=0。最终测试不得使用 `--maxfail` 隐藏剩余失败。

续作交付后，必须由未参与首轮或续作实现的全新外部 Cursor 会话完成原 B1B 全合同独立初验，并至少增加一
个实现者未用的分红/因子或 v1/v2 身份反例；之后才能进入主 Agent 终验。
