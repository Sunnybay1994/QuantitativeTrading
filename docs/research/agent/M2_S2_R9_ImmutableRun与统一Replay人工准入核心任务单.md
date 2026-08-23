# M2 S2 R9：Immutable Run 与统一 Replay 人工准入核心任务单

状态：metrics provenance 合同重冻返工与正常开发检查已完成；主 Agent 已接收，待集成合流；不代表 `PAPER_CANDIDATE` 或 PAPER 已获准

## 1. 目标与价值

- 为既有 lightweight research run 增加可复用的严格只读验真入口。
- 复用现有 M4 B6 统一市场事件 replay 与 B8 evidence-only admission，不自建撮合、收益模拟或第二套准入框架。
- 输出独立、不可执行的 S2 裁决；公共类型为未来 verified metrics provenance 预留
  `ELIGIBLE_FOR_HUMAN_ADMISSION`，但当前 API 不得产生该状态。
- 即使 replay 与 B8 自洽，当前指标仍未证明来自该 replay；正确结果保持 `RESEARCH_ONLY`。本包不改写原 run、
  不发布 `PAPER_CANDIDATE`、不启动 PAPER。

## 2. 现状与权威上下文

- `src/quant/research/lightweight_run.py` 已提供内容寻址的 `LightweightResearchRunV1` 和 no-clobber publisher，
  但只有 publisher 私有的 expected-bytes 对照，没有任意既有 bundle 的公共 fresh verifier。
- `quant.backtest.event_simulator.verify_simulation_result_identity` 已保留并完整重放 plans、market snapshots、
  initial account 与 config；它是本包唯一统一 replay 入口。
- `quant.research.strategy_admission.compare_strategy_candidates` 已提供 test-only、最坏场景、完整候选/指标集合的
  evidence-only admission；它能证明 caller 提供的指标集合自洽，但当前 `StrategyCandidate` 没有绑定 B6 replay
  或 verified B7 metrics provenance。`ADMIT`/`REJECT` 均不能单独成为本包的业务准入或拒绝依据。
- 历史 S2 run 的 `test_targets.parquet` 是测试窗口输出，不能冒充冻结前向 `target_weights.parquet`。
- 当前真实业务仍缺 2026-08-31 后的前向目标、对应 clean/PIT 来源和同一目标的统一 replay；本包只交付验证核心。

## 3. 冻结公共行为

### 3.1 lightweight run strict verifier

在 `lightweight_run.py` 新增：

```python
class LightweightResearchRunError(ValueError): ...

def verify_lightweight_research_run(*, run_root: Path) -> LightweightResearchRunV1: ...
```

入口必须：

1. 只读 `run_root/run.json` 与 manifest 列出的 outputs，不遍历项目 `data/`，不访问网络、账户或订单。
2. 要求 root 是非链接的真实目录，basename 精确等于 `run_id`；开始与结束时 root 实体相同。
3. `run.json` 必须是 canonical JSON、字段集合精确、可由公开 dataclass 重建，且 `run_id` 按既有
   `lightweight-research-run-id-v1` 公式重算一致。
4. 输出路径、顺序、size、SHA-256、exact tree 均一致；拒绝 missing/extra、路径逃逸、symlink/junction/reparse、
   输出间 hardlink/物理别名和稳定读取期间替换。
5. 对外只返回重新解析的 `LightweightResearchRunV1`；错误统一为
   `LIGHTWEIGHT_RESEARCH_RUN_INVALID`，且 `__cause__` / `__context__` 为空，不泄漏路径或内部异常。

### 3.2 S2 只读准入裁决

在新模块 `s2_paper_admission.py` 新增最小 API：

```python
S2PaperAdmissionStatus = Literal[
    "REJECTED", "RESEARCH_ONLY", "ELIGIBLE_FOR_HUMAN_ADMISSION"
]

@dataclass(frozen=True, slots=True)
class S2PaperAdmissionDecision:
    decision_id: str
    source_run_id: str
    status: S2PaperAdmissionStatus
    code: str
    replay_result_id: str | None
    admission_decision_identity: str | None
    checks: tuple[str, ...]

class S2PaperAdmissionError(ValueError): ...

def assess_s2_paper_admission(
    *,
    run_root: Path,
    replay_result: VerifiedSimulationResult | None,
    admission_subjects: tuple[StrategyCandidate, ...] | None,
    admission_context: AdmissionContext | None,
    admission_thresholds: AdmissionThresholds | None,
) -> S2PaperAdmissionDecision: ...
```

允许增加不具执行能力的窄只读 context-derivation helper，但不得增加 publisher、deploy、runner、queue、DB 或
gateway API。

判定规则：

1. 每次先调用 public run verifier；caller 不能传自报 run 或 output digest 绕过 fresh bytes。
2. source `REJECTED` 返回 `REJECTED`；source `RESEARCH_ONLY` 才可继续；已自报 `PAPER_CANDIDATE` 的输入不能
   自证，稳定拒绝。
3. replay、subjects/context/thresholds 必须“全缺或全有”。全缺时返回 `RESEARCH_ONLY`，表示证据尚未提供；
   部分存在属于无效输入并 fail closed。
4. 全有时必须 actual 调用 `verify_simulation_result_identity`，再 actual 调用
   `compare_strategy_candidates`；不得信 caller 自报 replay PASS 或 admission decision，不得缓存旧结论。
5. 只有 run outputs 含 exact `target_weights.parquet` 才可能继续；历史 `test_targets.parquet` 或其他文件名只可
   保持 `RESEARCH_ONLY`。
6. 统一 replay 的每个非空 scheduled `OrderPlan.target_identity` 必须 exact 等于 `run.run_id`；run id 已绑定
   `target_weights.parquet` 的 bytes。每个 scenario 至少有一个 scheduled plan，scenario 集合与 admission
   context exact 一致。
7. admission context 的四类 identity 必须从 proven replay 唯一派生并 exact 比较：
   - snapshot：绑定 ordered `market_snapshot_ids`；
   - window：绑定 config `event_sessions` 与 `terminal_date`；
   - rules：绑定 `config_id`、settlement-rule IDs、corporate-actions SHA 与 SH sessions；
   - costs：绑定 ordered planner-config identities。
   派生使用本模块固定版本的 canonical SHA-256；不得接受 caller 自报摘要。
8. candidate 集合必须含 `candidate_id == run.run_id`。当前 `StrategyCandidate`/B8 decision 的 metrics 没有
   proven replay/B7 provenance binding，因此 B8 `ADMIT`、`REJECT` 或选中任一 candidate 都只作诊断：source
   原始状态不是 `REJECTED` 时，统一返回 `RESEARCH_ONLY`，code 为
   `ADMISSION_METRICS_PROVENANCE_UNBOUND`，checks 必须含 `ADMISSION_METRICS_UNBOUND`。可保留重算后的
   `admission_decision_identity` 供审计，但不得据此晋级或拒绝。
9. 决策 identity 绑定上述所有输出字段；它是普通审计值，不是 capability。错误统一
   `S2_PAPER_ADMISSION_INVALID`，cause/context 为空。

### 3.3 实现中发现与合同重冻

- **现象**：真实 B6 replay、派生 context 和 target binding 全部通过时，caller 仍可构造任意漂亮的
  `ScenarioEvidence.metrics`，使 B8 产生自洽的 `ADMIT`；旧冻结规则会错误返回
  `ELIGIBLE_FOR_HUMAN_ADMISSION`。同理，任意差指标可产生不可信的 `REJECT`。
- **根因**：`StrategyCandidate.subject_identity` 只哈希 candidate/context/scenario/普通指标值；B8 decision 只比较
  这些自哈希值和 threshold，没有引用 `VerifiedSimulationResult.result_id`、scenario result IDs 或 verified B7
  metrics receipt。因此“replay 为真”与“用于 B8 的 metrics 来自该 replay”之间没有密码学/合同闭包。
- **最小复现**：保留同一个真实 replay/context/target，分别把 source/baseline return 改为任意高值、任意低值
  或让另一 candidate 获胜；B8 decision 随 caller 自填值变化，但 replay identity 完全不变。
- **重冻规则**：继续 actual 验证 B6、派生 context、验证 target/scenario，并 actual 重算 B8 供诊断；在新增公开、
  可验真的 metrics provenance 合同前，任何 B8 结果均不得改变 source `RESEARCH_ONLY`。不得在本任务中复制
  metrics 公式或伪造 B7 receipt 来填补缺口。
- **新增测试**：真实 replay/context + 漂亮指标仍 `RESEARCH_ONLY`；B8 `REJECT` 或选中另一 candidate 也仍
  `RESEARCH_ONLY`；三者均返回 `ADMISSION_METRICS_PROVENANCE_UNBOUND`。
- **通过条件**：当前 R9 通过条件是上述 fail-closed 行为稳定成立。未来只有存在公共 verified metrics provenance
  接口，能把完整 scenario metrics 精确绑定 proven replay/B7 identity，并另行冻结接口和反例后，才允许解锁
  `ELIGIBLE_FOR_HUMAN_ADMISSION`。

## 4. 明确非目标与禁止项

- 不改任何因子、目标权重、runner、既有 run 或其 outputs。
- 不实现 clean source binding；该接线等待根 repository 后续安全提交。
- 不自建市场事件 simulator、metrics engine、队列、数据库、账户、OMS、Gateway 或订单 I/O。
- 不 import 任一 `run_*` 私有 helper，不调用网络，不读取项目 `data/`。
- 不修改任何 `__init__.py`、配置、roadmap、共享 SSOT 或 `pyproject.toml`。
- 不把 replay 成功或 B8 `ADMIT`/`REJECT` 视为 provenance 已闭合；当前 API 不产生
  `ELIGIBLE_FOR_HUMAN_ADMISSION`，更不得表述为候选发布、PAPER 或实盘授权。

## 5. 文件白名单与所有权

唯一可写：

- `src/quant/research/s2_paper_admission.py`（新）
- `src/quant/research/lightweight_run.py`
- `tests/unit/test_m2_s2_paper_admission.py`（新）
- `tests/unit/test_lightweight_research_run.py`
- 本任务单
- `docs/research/agent/M2_S2_R9_ImmutableRun与统一Replay人工准入核心交付报告.md`

分支 / worktree / base：

- `codex/m2-s2-paper-admission-core`
- `artifacts/dev_worktrees/m2-s2-paper-admission-core`
- `cb2a0eb7b31384b0b263c83962ac923c06dcfc58`

## 6. 验证与反例

至少覆盖：

- strict verifier 正向；manifest/output tamper、missing/extra、非 canonical JSON、root-name mismatch、路径逃逸、
  symlink/reparse/hardlink alias、读取中实体替换稳定拒绝。
- `REJECTED`、全缺证据 `RESEARCH_ONLY`、缺 forward target `RESEARCH_ONLY`；真实 replay/context/target 加任意
  漂亮指标仍因 provenance 未绑定而 `RESEARCH_ONLY`。
- replay result forgery、另一 run/target identity、另一 scenario/context、部分 evidence、B8 `REJECT`、B8 选中
  另一 candidate、source 已是 `PAPER_CANDIDATE`；其中合法但未绑定的 B8 `REJECT`/另一 winner 不得据此拒绝
  source，而应稳定保持 `RESEARCH_ONLY`。
- hostile verifier/admission 异常递归图脱敏；ambient Decimal/输入 tuple 顺序不得改变裁决。
- 调用前后 source tree bytes 完全不变，API 不含 publish/deploy/order 能力。

正常开发检查：

```powershell
D:\Miniforge3\python.exe -m pytest tests/unit/test_lightweight_research_run.py tests/unit/test_m2_s2_paper_admission.py -q
D:\Miniforge3\python.exe -m ruff check src/quant/research/lightweight_run.py src/quant/research/s2_paper_admission.py tests/unit/test_lightweight_research_run.py tests/unit/test_m2_s2_paper_admission.py
D:\Miniforge3\python.exe -m mypy src/quant/research/lightweight_run.py src/quant/research/s2_paper_admission.py
```

测试进程与 M4 串行使用 CPU 8–11、BelowNormal；不机械运行全量测试。

## 7. 安全、停止与交付

- 若现有 B6/B8 API 无法在白名单内诚实复用、必须复制 target/metrics/模拟公式、必须访问 data/account/order、
  或必须修改 forbidden 文件，立即停止并回报，不迁就任务书。
- 若真实业务证据尚未满足，正确结果是 `RESEARCH_ONLY`，不是用 fixture 或自报摘要补洞。
- 本包无外部状态写入；失败不得修改 source run 或产生候选目录。
- 交付报告须列明 exact diff、实际检查结果、未关闭的 clean/PIT/forward/opening 前置和范围外改动。
- 2026-08-18 前外部 Agent 暂停；由主 Agent/内部并行 subagent 按普通开发规范完成。无需独立初验，内部
  subagent 不模拟“独立实现 → 独立初验”。
