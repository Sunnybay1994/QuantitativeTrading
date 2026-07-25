# 2026-07-22 Codex 至 Cursor：后续整体交接任务书与启动 Prompt

## 1. 接任角色

你是本项目后续工作的外部 Cursor **协调 Agent**。先保护当前脏工作树、恢复可重现状态，再按
`AGENTS.md` 的四阶段职责分离继续推进。你不得把同一会话同时当作实现者和独立初验者；高风险实现默认使用
全新 `cursor-grok-4.5-high` 会话，独立初验使用另一全新会话，最终 Gate 仍需主/协调 Agent 复核。

用户要求 A 股全流程优先、暂停内部 subagent，可并行调用外部 Cursor 会话；Windows PowerShell 7 与
`D:\Miniforge3\python.exe` 可作反馈环，WSL Miniforge `base` 是 Linux/Gate 权威。Tushare 2000 积分档 API
已获持续授权，但必须有界、复用 raw/receipt、不得输出 token。

## 2. 接任前必读与保护

按顺序完整阅读：

1. `AGENTS.md`、`.ai/README.md`、`.ai/coding_rules.md`；
2. `docs/CODEX_HANDOFF.md` 的 2026-07-22 最新摘要、§5.2、§9.2；
3. BENCH-B1B 主任务书、R1–R5 任务/交付/复验报告；
4. `项目实施路线图.md` 与 M3 当前总览中直接相关条目。

先运行只读检查：`git status --short`、目标文件的 whitespace-insensitive diff、Windows/WSL 进程检查。当前
工作树包含多轮合法未提交改动，禁止 reset、checkout、覆盖或批量换行。`archive/legacy_pre_greenfield/`
和 `data/legacy/` 不参与任务。

## 3. 已完成且不得重做的证据

- B1B 外部实现、R1/R3/R4 返工与独立复验已完成；WSL base 主验为四组
  `214 + 250 + 31 + 24 = 519 passed`，Ruff/mypy/diff Gate 通过。
- 正式 HISTORY 计划为 `637 symbols / 3190 requests`；旧 3185 个股票 identity 保持不变，新五项全部是
  510300.SH：三段 `fund_adj`、一个 `fund_div`、一个 `fund_daily`。
- 五个正式 identity 的 `intent/candidate/receipt` 均已提交，行数分别为 791/972/851、22、2614。
  **不得再次调用这五个 API**；恢复执行必须先验真现有 receipt，预期新增请求为零。
- 五响应已独立严格映射成功：2614 行、2015-10-09..2026-07-10、snapshot
  `a4cd3f23aab767e4f1af090cc3a283df8570ebd59af8a402e4173653fa28582c`。不要再把 benchmark mapper
  当作未验证假设。
- R5 外部实现已落盘，只改 `tests/unit/test_m3_g1_workflow.py` 与自己的交付报告；实现者自测 resume 两项
  `2 passed in 42.02s`、回归两项 `2 passed in 3659.40s`、Ruff/diff 通过。R5 **尚缺独立初验和协调
  Agent 主验**。

## 4. 当前真实阻塞

正式 full candidate 失败：

```text
WSL status: 1993.4s -> INSPECT:G1_WORKFLOW_QUALITY_FAILED
Windows diagnostic: 1457.7s -> G1_CANDIDATE_COMPONENT_INVALID
```

后续一次零网络组件诊断已把首个失败收窄到 `corporate_action_selection`：
`M3G1ExecutionFactError(code=G1_CORPORATE_ACTION_RESULT_INVALID)`，触发点为
`m3_execution_facts.py::_assert_ledger_evidence_closure`。现有证据表明 ledger 的 `event_id` 与根据所选 evidence
重新计算的 `_event_id_sha256(...)` 不一致；daily/adj_factor 严格映射、`stk_limit`、`suspend` 和 benchmark
在此之前均已通过。诊断摘要见 `artifacts/g1_component_diag_20260722/summary.json`，记录见
`docs/agent/M3_G1_CANDIDATE_COMPONENT_INVALID_零网络组件级诊断记录.md`。下一步直接围绕该身份闭包冻结最小
返工任务，禁止重新跑五个 510300 请求或先重复 full build。

环境另有独立 PUBLISH blocker：Ubuntu 实际为 WSL1，内核 `4.4.0-22621-Microsoft`，根为 `wslfs`，
`RENAME_NOREPLACE` 探针 False；Windows 报告固件虚拟化 False。Windows/DrvFS 绿测不能代替 Linux ext4
不可变发布。需要用户在 BIOS/UEFI 启用 VT-x/虚拟化并迁移或新建 WSL2 后，才可复验 ext4 发布条件。

## 5. 接任执行顺序

1. **R5 独立初验**：新开只读 Cursor 会话，唯一可写自己的复验报告；确认计划非空、真实跨过基金 identity、
   resume 前缀复用、最终零新增，且 monkeypatch 不泄漏到其他测试。失败则形成返工闭环。
2. **吸收既有零网络诊断**：先读取诊断任务、记录和 `summary.json`，复核
   `corporate_action_selection` 的 ledger/evidence `event_id` 闭包最小复现；不得请求 Tushare/BaoStock，
   不得修改正式 raw/journal/receipt，也不得用重复 full build 代替根因分析。
3. **按根因分流**：
   - 实现缺陷：冻结最小返工任务书 → 全新外部实现 → 另一全新外部初验 → 协调 Agent 主验；
   - 正式数据缺陷：保留 raw 事实，写明现象/根因/规则/最小复现/新增测试/通过条件；禁止静默填充；
   - 任务书或 SSOT 错误：先修权威合同，再下发实现。
4. full candidate 与 HISTORY stage 真正通过后，才运行正式 REFERENCE、PREPARE。所有长命令使用持久日志和
   rc，或至少一小时工具窗口；已知 full candidate 单次约 24–34 分钟，full fake workflow 约 61–68 分钟，
   禁止分钟级空日志轮询。
5. PUBLISH 等用户完成 WSL2/ext4 条件；取得真实 `VerifiedG1Release` 前禁止真实 G2A。之后按
   `G2A→G2B→G2C→G3A→G3B→G4…→G9`，再推进 M4 A 股 Paper 全闭环。
6. 每个可验收子包同步任务、交付、初验、主验、路线图/交接；测试 fixture 绿测不得写成真实 Gate 通过。

## 6. 可直接复制的启动 Prompt

```text
你是 QuantitativeTrading 项目的外部 Cursor 协调 Agent，接替 Codex 继续后续全部工程任务。

工作区：F:\AI_Coding\QuantitativeTrading
WSL 同目录：/home/mabw/AI_Coding_win/QuantitativeTrading

先完整阅读 AGENTS.md、.ai/README.md、.ai/coding_rules.md、docs/CODEX_HANDOFF.md，以及
docs/agent/20260722_Codex至Cursor后续整体交接任务书与启动Prompt.md。先只读运行 git status、定向 diff 和
进程检查，保护所有现有未提交改动。禁止 reset/checkout、批量换行、读取或输出 token、重复五个 510300
正式 API 请求。

当前第一优先级：
1) 用一个全新的、未参与 R5 实现的 cursor-grok-4.5-high 会话，只读独立初验 R5 最小 fixture，并只写唯一
复验报告；
2) 直接吸收已有零网络诊断证据：artifacts/g1_component_diag_20260722/summary.json 和
docs/agent/M3_G1_CANDIDATE_COMPONENT_INVALID_零网络组件级诊断记录.md。首个失败已定位为
corporate_action_selection 的 G1_CORPORATE_ACTION_RESULT_INVALID，触发于
m3_execution_facts.py::_assert_ledger_evidence_closure；ledger event_id 与根据所选 evidence 重算的
_event_id_sha256(...) 不一致。先做最小复现和根因确认，再冻结最小返工任务。daily/adj_factor 严格映射、
stk_limit、suspend、benchmark 已在此前通过；510300 五响应 mapper 也已正式通过，禁止重复调查或请求；
3) 根据证据走“全新外部实现 → 另一全新外部独立初验 → 你最终验收”的强制闭环。

正式 HISTORY receipts 已是 3190/3190；full candidate 仍失败，所以禁止进入 REFERENCE/PREPARE/PUBLISH。
当前 Ubuntu 是 WSL1/wslfs 且固件虚拟化关闭，RENAME_NOREPLACE=False；禁止降低发布合同或用 Windows
绿测冒充 ext4 Gate。需要主机变更时向用户明确报告并等待。

按任务书 §5 顺序持续推进，A 股优先。每轮只返回压缩进度、证据、改动文件、验证结果、风险和下一步；
不得用实现者自测替代独立初验，不得在真实 Gate 未通过时更新为完成。
```

## 7. 交接执行方式与误启动记录

用户于 2026-07-22 说明：Codex 只提供交接文档和可复制 prompt，由用户在外部自行执行；全部任务完成后，
用户再把结果交回 Codex 做最终验收。Codex 不代为启动 Cursor 会话。

此前误启动的 Cursor 协调会话及其 WSL 定向 pytest 已停止。终止前留下的压缩输出保存在：

- `artifacts/agent_handoff/20260722_cursor_successor/stdout.log`
- `artifacts/agent_handoff/20260722_cursor_successor/stderr.log`

该会话留下的组件诊断可作为只读证据复用，但不构成正式实现交付或独立初验；R5 独立初验报告尚未生成，
状态仍为待验收。外部执行应使用用户新开的会话，从 §6 prompt 开始。
