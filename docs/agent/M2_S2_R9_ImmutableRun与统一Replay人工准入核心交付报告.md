# M2 S2 R9：Immutable Run 与统一 Replay 人工准入核心交付报告

状态：metrics provenance fail-closed 返工与正常开发检查完成；主 Agent 已接收，待集成合流

本报告只说明 S2 只读准入核心已实现，不表示已产生 `PAPER_CANDIDATE`，也不表示 PAPER 或实盘已获准。

## 1. 分支、基线与范围

- worktree：`artifacts/dev_worktrees/m2-s2-paper-admission-core`
- branch：`codex/m2-s2-paper-admission-core`
- base：`cb2a0eb7b31384b0b263c83962ac923c06dcfc58`
- 实现方式：外部 Agent 暂停期间的内部并行实现任务，不设置或模拟独立初验。
- 未修改 `__init__.py`、配置、roadmap、共享 SSOT 或 `pyproject.toml`；未创建 runner、publisher、撮合器、
  metrics engine、队列、数据库、账户、OMS、Gateway 或订单 I/O。

唯一改动文件：

- `src/quant/research/lightweight_run.py`
- `src/quant/research/s2_paper_admission.py`（新）
- `tests/unit/test_lightweight_research_run.py`
- `tests/unit/test_m2_s2_paper_admission.py`（新）
- `docs/agent/M2_S2_R9_ImmutableRun与统一Replay人工准入核心任务单.md`
- 本报告

## 2. 实现结果

### 2.1 Lightweight run fresh verifier

新增 `LightweightResearchRunError` 与 `verify_lightweight_research_run(run_root=...)`：

- 只读并重新解析 canonical `run.json`，精确核对字段集合、嵌套 dataclass、日期表示和既有
  `lightweight-research-run-id-v1` 身份；
- root 名称必须等于 `run_id`，开始/结束 root 实体必须一致；
- manifest 输出集合、完整目录树、size、SHA-256 必须一致；
- 拒绝 missing/extra、路径逃逸、symlink/junction/reparse、硬链接及物理别名；
- 对文件执行 lstat → 打开句柄/fstat → 稳定读取 → lstat，并在完成时重新扫描树；
- Windows 的 lstat/fstat 纳秒时间表示可能精度不同，因此句柄对应关系只比较实体、mode、size、nlink，
  路径读取前后仍比较实体、mtime/ctime、size 和 nlink，避免把同一 NTFS 文件误判为替换；
- 所有对外失败统一为 `LIGHTWEIGHT_RESEARCH_RUN_INVALID`，`__cause__` 和 `__context__` 均为空。

### 2.2 S2 evidence-only human-admission assessment

新增 `s2_paper_admission.py`：

- 公开 `derive_s2_replay_context_identities`，先实际调用 B6
  `verify_simulation_result_identity`，再从 proven replay 唯一派生 snapshot/window/rules/costs identities；
- 公开 `assess_s2_paper_admission`，每次先 fresh verify source run；证据必须全缺或全有，部分证据 fail closed；
- 全量证据路径实际重放 B6，并实际重新调用 B8 `compare_strategy_candidates`，不信任 caller 自报结论；
- 每个 replay scenario 必须至少有一个 scheduled plan，所有 plan 的 `target_identity` 必须等于 source
  `run_id`，scenario 与 B8 context 必须精确一致；
- 实现中确认 B8 的 caller-supplied metrics 尚未绑定 proven replay 或 verified B7 metrics receipt；因此
  `target_weights.parquet` 存在且 B8 选中 source 也只能保持 `RESEARCH_ONLY`；
- B8 `ADMIT`、`REJECT` 或选中其他 candidate 均只作诊断，不据此晋级或拒绝；完整证据路径稳定返回
  `ADMISSION_METRICS_PROVENANCE_UNBOUND`，checks 含 `ADMISSION_METRICS_UNBOUND`，同时保留重算后的
  `admission_decision_identity` 供审计；
- `test_targets.parquet` 仍不是 forward target；source 自报 `PAPER_CANDIDATE` 不能自证；只有未来新增公共、
  可验真的 replay/B7 metrics provenance 合同后，才允许另行解锁 `ELIGIBLE_FOR_HUMAN_ADMISSION`；
- 决策 identity 绑定所有公开输出字段；固定 Decimal context，避免 caller ambient Decimal 精度改变裁决；
- 对外无发布、部署、订单或 Gateway 能力；错误统一为 `S2_PAPER_ADMISSION_INVALID` 且异常链脱敏。

### 2.3 实现中发现与返工

初版实现错误地把 B8 decision 当成了已绑定 replay 的指标证据。主审反例表明：caller 可以保持真实
replay/context/target 不变，只填写漂亮的 source metrics，即得到自洽 B8 `ADMIT`；也可填写差指标造成不可信
`REJECT`。根因是 `StrategyCandidate.subject_identity` 只绑定普通指标值，没有绑定 B6 result 或 B7 metrics
provenance。已按任务单 §3.3 重冻：保留 actual B6/B8 诊断，当前 API 永不返回 eligibility，也不依据未绑定
metrics 拒绝 source `RESEARCH_ONLY`。

## 3. 最终开发检查

所有实际 Python 承载均为 Windows Miniforge，单实例，`BelowNormal`，affinity `0xF00`（CPU 8–11），
线程上限 2，显式 `PYTHONPATH=<本 worktree>\src`。以下结果全部产生于 metrics provenance 重冻返工之后：

1. 定向 pytest：
   `D:\Miniforge3\python.exe -m pytest tests/unit/test_lightweight_research_run.py tests/unit/test_m2_s2_paper_admission.py -q`
   - PID 2984，exit 0；`24 passed, 1 skipped`，12.23 秒；stderr 空。
   - 唯一 skip：当前 Windows 宿主无创建 symbolic link 权限；hardlink、实体替换、tree tamper 等反例通过。
   - 2353 条 warning 均来自 Pandera/Polars 的既有 `concat how='horizontal'` 弃用提示。
2. Ruff：
   `D:\Miniforge3\python.exe -m ruff check` 加上述四个生产/测试文件。
   - PID 30680，exit 0；`All checks passed!`；stderr 空。
3. mypy：
   `D:\Miniforge3\python.exe -m mypy src/quant/research/lightweight_run.py src/quant/research/s2_paper_admission.py`
   - PID 19328，exit 0；`Success: no issues found in 2 source files`；stderr 空。
4. cold import：全新解释器从本 worktree 导入两个模块并断言两个 public callable。
   - PID 12396，exit 0；两个 `__file__` 均位于本 S2 worktree；stderr 空。
5. 残留巡检：`NO_0xF00_PYTHON_OR_SHELL_RESIDUE`。

返工后的用例明确覆盖：真实 replay/context 加漂亮指标仍 `RESEARCH_ONLY`；B8 `REJECT` 或另一 candidate 获胜
也不据此拒绝 source；三者 code 均为 `ADMISSION_METRICS_PROVENANCE_UNBOUND` 且 checks 含
`ADMISSION_METRICS_UNBOUND`。

## 4. 未关闭前置与风险

- 尚无 2026-08-31 收盘后真实冻结前向 `target_weights.parquet`。
- 本包没有实现 clean/PIT source binding；仍须后续 repository 安全提交与接线。
- 同一真实前向目标的统一 replay、下一交易时段 opening facts 和人工准入尚未发生。
- 缺少把完整 scenario metrics 绑定 B6 result/B7 receipt 的公共 verified provenance 接口；这是当前禁止
  eligibility 的直接合同阻塞，不得用自报 digest 或复制 metrics 公式绕过。
- 只读 actual 审计确认：B6/B7 能逐 candidate 绑定 `result_id`、`metrics_id` 与 `scenario_result_id`，但当前
  B8 `StrategyCandidate` 不保存这些身份。未来最小接口应接收逐候选 `CandidateReplay`（candidate/target
  identity + `VerifiedSimulationResult`），内部 fresh 构建 `TradingMetrics`，并把上述三层 identity 写入 B8
  evidence，不能继续接收 caller 自填的普通 metrics 作为准入事实。
- B7 book curve 不是 market NAV，不能改名冒充通用 return/drawdown；未来只可投影语义明确的 book/execution
  metrics。多币种、`None` 或需要经济 NAV 的场景必须 fail closed，直到存在单独冻结且可验真的估值合同。
- 当前宿主未实际执行 symlink 反例（权限不足）；生产实现仍同时检查 symlink 与 Windows reparse attribute，
  hardlink 和稳定读取替换反例已执行。
- 本变更当前只提供 fail-closed 诊断，不声称“可提交人工准入”，不自动改写 run，不发布候选，不启动 PAPER。

## 5. 交付状态

- worktree 保持未提交，供主 Agent 接收并形成安全提交点。
- CPU 8–11 串行槽已明确释放；最终巡检为 `NO_0xF00_PYTHON_OR_SHELL_RESIDUE`。
