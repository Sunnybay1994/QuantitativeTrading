# M4 P8 RUN-0B2A2：P7 Durable Risk Exact Completeness 独立复验报告

日期：2026-08-09  
状态：**PASS，可进入主 Agent 最终验收**  
角色：未参与 B2A2 实现的全新独立只读复验

## 1. 结论

B2A2 已按冻结合同把 P7 风控事实唯一收缩到 `RecoveryResult.risk_receipts`：公开 builder 不再接受 caller
`risk_decisions`，fresh recovery、公共 semantic verifier、ORDER-only risk line 投影以及 P8 retained v2 wire
形成同一条 exact completeness 链。本轮没有发现新的阻断。

本结论只表示 development 工程合同通过；不代表 RUN-0B2 正式装配、真实 28 日 PAPER soak、正式 scheduler、
WSL2/ext4 或 M4 Gate 通过。M4 仍应保持 `WAITING_FOR_SOAK_EVIDENCE`。

## 2. 合同与代码核对

- `build_execution_report(*, recovery, reconciliation, as_of)` 的签名已删除 `risk_decisions`，没有 optional、
  overload、`**kwargs` 或兼容入口；仓库搜索只剩测试中的显式旧参数拒绝反例。
- `_verify_recovery` 要求 exact `RecoveryResult`，并把包括 `risk_receipts` 在内的全部字段 fresh 传给构造器；
  `RecoveryResult.__post_init__` 随即调用 B2A1 公共 `verify_risk_receipt_semantic_closure` 并重算
  `recovery_id`。
- P7 在 totals 与 report identity 构造前再次调用同一公共 semantic verifier。该 verifier exact 检查 receipt、
  command、cancel runtime type，global sequence/previous、per-key counter chain，以及 ORDER/CANCEL 对 retained
  command/cancel 的 exact-once owner；missing、extra、duplicate、cross-plan、cross-kind 和协调 whole-rehash 后的
  非闭合状态均 fail closed。
- risk line 只投影 `transition_kind == "ORDER"` 且 exact `DurableOrderRiskDecision` 的 `rule_results`；CANCEL
  receipt 参与 recovery closure/identity，但不产生 pre-trade rule line。投影只保留不可逆
  `subject_identity`，`detail` 不进入 report、canonical bytes 或 repr。
- `soak.py` 的 session/fault recovery facts 分别使用显式 v2 schema；encoder 保留每条 receipt 的公共 strict
  canonical wire，decoder 要求 exact field set、调用公共 strict decoder，并 fresh 构造 `RecoveryResult`。
  旧 v1 或缺少 `risk_receipts` 的 payload 没有兼容回填旁路。
- P8 session receipt、facts digest 与独立 append anchor 继续绑定 retained closure。现有 fully-valid replacement
  回归在 receipt/facts 内部全部协调重算后，仍由独立 anchor 拒绝；P8 v2 演进没有绕开该边界。
- P7 源文件无 `open`、socket、SQLite 或墙钟读取调用。公开 builder/encoder 的禁止 open/socket/SQLite 探针通过；
  任意下游异常均在离开 active `except` 后统一成为 detached `EXECUTION_REPORT_INVALID`。

## 3. 独立对抗反例

本复验另行运行了一个未写入仓库、实现者未使用的递归 hostile exception graph 探针：把 P7 直接依赖的公共
semantic verifier 替换为 `ValueError("outer") from RuntimeError(marker)`，其中 marker 同时包含 TOKEN、Windows
私有路径、SQLite 文件名和 SQL 文本。`build_execution_report` 只返回 exact
`ExecutionReportError("EXECUTION_REPORT_INVALID")`；`__cause__` 与 `__context__` 均为 `None`，递归格式化
traceback 和异常 repr 中均不存在 marker。结果：`HOSTILE_RECURSIVE_EXCEPTION_GRAPH_PASS`。

此外，完整定向组覆盖并通过：caller 旧参数拒绝；空 receipt 配非空 command；receipt canonical bytes 漂移；
retained v2 缺字段/额外 legacy 字段；B2A1 missing/extra/duplicate/cross-plan/cross-kind/whole-rehash semantic
closure；以及合法但不同 recovery/report/facts/session closure 整体替换后由独立 anchor 拒绝。

## 4. 可重现验证

Windows 原生 `D:\Miniforge3\python.exe`，`PYTHONPATH=src`：

- `pytest tests/unit/test_risk_wire.py tests/unit/test_reconcile.py tests/unit/test_execution_report.py tests/unit/test_execution_soak.py -q`
  → **89 passed, 1 skipped**；
- 白名单 Ruff → **All checks passed**；
- `execution_report.py`、`soak.py` mypy → **Success: no issues found in 2 source files**；
- 独立 hostile recursive exception graph 探针 → **PASS**。

WSL Miniforge base，`/mnt/f/.../m3-g8ab-prereq`：

- 同组定向 pytest → **90 passed**；
- 同组 Ruff → **All checks passed**；
- 同组生产 mypy → **Success: no issues found in 2 source files**；
- `findmnt -T /mnt/f` → `drvfs rw,noatime,uid=1000,gid=1000,case=off`。

## 5. 范围与诚实边界

本轮严格保持生产代码和实现者测试只读，只新增本报告；未修改 B2A1、formal root、journal、runner、scheduler
或其他脏文件，未联网、未 add/commit。DrvFS 结果只是 Windows/WSL 双平台 development 兼容证据，不是
WSL2/ext4 Gate。拥有完整 evidence root 与独立 anchor 写权限的主体仍超出当前自哈希/独立目录信任模型；
本报告不把 development closure 表述为正式来源防伪或正式 PAPER Gate。
