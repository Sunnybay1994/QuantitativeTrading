# M2-EVAL-R16 PIT 冗余日期覆盖对称闭包任务与交付记录

## 1. 静态任务边界

- 状态：`STATIC_DONE_REWORK`；本记录只表示静态代码、测试和文档变更完成，不表示 Python、Gate、真实数据或研究运行通过。
- 模式：`STATIC_ONLY`；资源：`NONE`；`trial_delta=0`。
- exact base：`db98f1cae00009922bc91e044e711cce11b09cd7`。
- worktree：`artifacts/dev_worktrees/m2-eval-r16-pit-redundancy-coverage`；继续使用既有分支，不创建新
  worktree、分支或 Agent。
- 本包只关闭首个 PIT direct-call chain C 的日期 coverage 对称聚合；不修改 classic/shared evaluator、R3、
  阈值、公式、方向、成本、coverage 阈值、配置/run schema 或输出 schema。

精确变更路径只有：

1. `src/quant/research/run_pit_quality_factors.py`；
2. `tests/unit/test_run_pit_quality_factors.py`；
3. 本记录；
4. `docs/research/roadmaps/M2_策略与因子库并行建设路线图.md` 的本包状态 hunk。

## 2. 冻结合同

PIT summary 的每个候选从 `factor_a` 与 `factor_b` 两侧收集全部 incident pairs；每个 pair 的既有
`signal_date_coverage_passed` 必须是严格 Boolean，候选只有在所有 incident pairs 均为 `True` 时通过。
无 incident、缺失覆盖或 malformed 输入 fail-closed；summary 的候选行集与输入顺序保持不变，summary 外的
reference/control 不产生行。重复或 reverse-duplicate pair 不制造候选重复行，任一 `False` 仍拒绝。
只有 `RESEARCH_ONLY` 可因该门禁变为 `REJECTED`，已有 `REJECTED` 不升级。

## 3. 静态实现与反例覆盖

- gate 以双向 incident projection 聚合，使用左侧 summary join 并保留 summary 顺序；空 incident 聚合为拒绝。
- 对 summary 重复 factor、缺失 pair 字段、null/non-Boolean coverage 以及无法唯一聚合的输入 fail-closed。
- 静态测试覆盖 factor_b false、a/b 交换、多个 pair 的 all/one-false、缺失 reference、无 incident、缺失字段、
  null/non-Boolean coverage、重复 summary factor、duplicate/reverse-duplicate pair、factor_a 缺月和已有
  `REJECTED` 不升级。

## 4. 验证边界

- 仅允许进行静态 diff/path/whitespace 检查；禁止运行 Python、pytest、Ruff、mypy、cold import、数据 I/O、网络、PAPER 或提交。
- 本包不修改 `artifacts/agent_dispatch`；parent 负责 status/mapping、独立初验、主验和后续合流。

## 5. R4 rework closure

- 现象：首轮 gate 已对 pair 两侧做对称 coverage 聚合，但 `research_status` 未限制为冻结域，summary factor 与
  pair endpoint 也可为空字符串；这允许 malformed identity 进入 join/状态门禁。
- 根因：首轮只校验 factor 列的类型/唯一性与 coverage 类型，没有把 status domain、null/empty identifier 作为
  进入聚合前的结构合同；输出列碰撞虽已有 guard，缺少 focused regression evidence。
- 应遵循规则：`research_status`、`factor`、`factor_a`、`factor_b` 必须 exact `pl.String`、非 null；三个标识符
  必须非空；status 值只能是 `RESEARCH_ONLY` 或 `REJECTED`；普通非空 reference absent from summary 仍允许且不
  产生新行；所有违反均抛出既有稳定 `ValueError`。
- 最小复现：`research_status="HOLD"`、null/categorical/enum/non-string status、空 summary factor、空 factor_a 或
  factor_b；以及 summary 已含 `redundancy_signal_coverage_passed` 时再次生成该列。
- 新增静态测试：覆盖 unexpected/null/non-string/categorical/enum status、已有 `REJECTED` + true、三个空标识符、
  unrelated diagnostic column preservation 与 output-column collision。
- 通过条件：F1/F2 反例均稳定 fail-closed；合法非空 summary 保持行集/顺序/诊断列，已有 `REJECTED` 不升级；
  roadmap 仍只宣称 `STATIC_DONE`/`STATIC_ONLY`，不扩大到 runtime/Gate。

本轮完成状态：`STATIC_DONE_REWORK`。

## 6. 管理器交接与一次性验证载荷

- 本次只记录既有 validation-only 载荷，不改变静态状态：`retry01-20260825-132714992` 在 exact worktree、
  `PYTHONPATH=<worktree>/src`、`D:\Miniforge3\python.exe`、BelowNormal、`0xF00`、numeric thread cap `2`
  下单实例运行。Stage 01 identity probe 通过；Stage 02 collect-only 收集 `33` 项；Stage 03 指定 `12` 个
  node 全部通过（`22 passed`）；Stage 04 Ruff `All checks passed!`；Stage 05 mypy `Success: no issues found`
  （`1` source file）；Stage 06 cold import 通过。上述六阶段均 exit `0`，carrier 均报告 affinity `0xF00`、
  priority `BelowNormal`、无 resource error。
- Stage 07 只读 exact5/status/diff/temp/process 证据在 `Get-CimInstance Win32_Process` 处停止：Windows
  permission-only boundary 返回 `PermissionDenied`、HRESULT `0x80041003`；该失败不改变代码、测试、文档或
  进程状态，不能宣称 Stage 07 或 Gate 通过。Finance writer PID `7692` 未被写入、暂停、调度或修改。
- 管理器 exact5 closure：本记录是唯一允许更新的交付路径；source、test、roadmap 和独立初验报告只读保留，
  独立初验报告不由实现者改写；本次提交白名单仍严格限定 exact5，`artifacts/agent_dispatch` 不在范围内。

### 6.1 验证载荷 SHA256（保留至提交证据落盘）

| stage | stdout（bytes / SHA256） | stderr（bytes / SHA256） | exit（bytes / SHA256） |
|---|---|---|---|
| 01 identity | 2067 / `EDBB7CADE739A98096E14F887C22D88BFED6ABE4A940F5CA836BD4DFBF3388A2` | 0 / `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855` | 1 / `5FECEB66FFC86F38D952786C6D696C79C2DBC239DD4E91B46729D73A27FB57E9` |
| 02 collect-only | 4356 / `0B3025D4BFD8571A27088CA622571242800C8EDCA10D2FE8DBE2A60A2B127316` | 0 / `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855` | 1 / `5FECEB66FFC86F38D952786C6D696C79C2DBC239DD4E91B46729D73A27FB57E9` |
| 03 selected tests | 2471 / `DCBE72249CC1DB36E06FB045DDB97272196E9E69E10174F59ED5AEDD4709EF0F` | 0 / `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855` | 1 / `5FECEB66FFC86F38D952786C6D696C79C2DBC239DD4E91B46729D73A27FB57E9` |
| 04 Ruff | 709 / `8E89C9337EBB3564E8D3E2C265C6FA903B4D82DFB5248F577F51677140EDA0F8` | 0 / `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855` | 1 / `5FECEB66FFC86F38D952786C6D696C79C2DBC239DD4E91B46729D73A27FB57E9` |
| 05 mypy | 680 / `6E282B690A3CE800DF06BF7D9FE15E05714CC3EFADE265EF34E7A5809541AEB7` | 0 / `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855` | 1 / `5FECEB66FFC86F38D952786C6D696C79C2DBC239DD4E91B46729D73A27FB57E9` |
| 06 cold import | 1277 / `45C371623BA0586F623B2DB3C80C78B0C2C745D6C2ACE0B53E1481314453278B` | 0 / `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855` | 1 / `5FECEB66FFC86F38D952786C6D696C79C2DBC239DD4E91B46729D73A27FB57E9` |
| 07 exact5 boundary | 5013 / `FB03CAEE2BD319280053F5C4D0A7C81B11233B58B4AE69562B9D55A10B8E2E23` | 1310 / `A92B4776ACE4B1B322D9A8285B64CF1CC06B06BA6ED26290367B6D790AC34651` | 1 / `6B86B273FF34FCE19D6B804EFF5A3F5747ADA4EAA22F1D49C01E52DDB7875B4B` |

首轮 carrier 的 identity stdout 也保留：`artifacts/test_tmp/m2-eval-r16-validation-logs/20260825-131826902-stage01-identity-probe.stdout.log`，
`1495` bytes，SHA256 `1A3BA1B11E79666755B37431C60992B7B5FFB5396F3A2D4FD8C58C1E6E9B8517`。
