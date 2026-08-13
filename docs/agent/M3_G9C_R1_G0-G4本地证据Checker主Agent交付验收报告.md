# M3 G9C R1 G0–G4 本地证据 Checker 主 Agent 交付验收报告

日期：2026-08-13
结论：**工程实现完成；允许继续 G9D；不代表真实 G9 或 M3 Gate 通过**

## 1. 目标与边界

本轮新增 G9C 本地 checker，只消费 G9B 已定位的 receipt、`VerifiedAcceptanceSubject`、当前严格配置和显式
artifact root registry。它固定返回 G0–G4 五个 `GateResultV1`，不扫描目录、不重算 DataFrame 公式、不接收
caller 自报 GateResult，也不把负 IC/收益当工程失败。

当前按用户指示由主 Agent 串行开发并执行正常工程验证，没有安排外部 Agent 或内部 subagent，也没有把
主 Agent 自测包装为“独立初验”。Linux/ext4 不在当前目标范围内。

## 2. 实现

- 新增 `src/quant/research/m3/acceptance_upstream.py`：
  - `audit_acceptance_upstream` 与稳定脱敏错误 `M3_ACCEPTANCE_UPSTREAM_INVALID`；
  - EvidencePlan 与 subject/config identity 必须重新构造后精确相等；
  - G0–G4 receipt 分别走 `verify_stage_receipt_with_bytes`；
  - receipt 输出分别走 readiness、snapshot、provider、provider-validation、label、reconciliation、experiment、
    folds 的生产 strict reader；
  - 一个 Gate 上游无效时只记录稳定 `UPSTREAM_INVALID`，其他独立 Gate 继续检查；
  - issue/evidence 固定排序、去重，失败不泄露路径或异常文本。
- `readiness_evidence.py` 新增窄只读 `read_readiness_evidence_report`，复用原有 `_strict_json` 与 report
  解析内核，没有新增第二份 Schema/序列化格式。
- `acceptance.py` 修复 G9B EvidencePlan 中 formal receipt stage `backtest-plan` 与 Stage registry key
  `backtest_plan` 的映射。修复前任何完整 subject 都会稳定失败为 `M3_ACCEPTANCE_PLAN_INVALID`。
- `quant.research.m3` 使用既有 lazy import 方式安全导出两个 G9C API 和 readiness reader。

## 3. 覆盖的关键反例

- 严格 fake G0–G4 完整闭包五 Gate 全 PASS；
- 单个 reconciliation 输出在 receipt 发布后漂移，仅 G3 FAIL，其他 Gate 不被掩盖；
- `meta.enabled=false` 只产生 G0 `CONFIG_DISABLED`；
- provider 60 emitted keys / 420 comparisons 漂移只产生 G2 failure；
- caller 用 `dataclasses.replace` 重构 exact provider subject、但 receipt 输出字节未改变时，G2 因生产 reader
  读回值不一致而拒绝；
- 非法 caller 输入只返回稳定错误，`__cause__`/`__context__` 均为 `None`。

## 4. 验证

Windows Miniforge、显式绑定当前工作树 `src`：

- `pytest test_m3_acceptance_upstream.py test_m3_acceptance_contracts.py test_m3_readiness_evidence.py`：
  **20 passed**；
- Ruff：修改的 4 个生产文件和 3 个测试文件通过；
- mypy：`acceptance.py`、`acceptance_upstream.py`、`readiness_evidence.py`、`m3/__init__.py` 通过；
- fresh `python -I` cold import：`G9C_COLD_IMPORT_PASS`，未加载 Qlib、LightGBM、MLflow；
- `git diff --check`：退出 0，仅现有 Windows LF/CRLF 提示。

pytest cache 因该历史工作树目录权限产生 warning，但定向测试使用系统 temp 作为 `--basetemp`，断言与退出码
均正常；该 warning 不作为 Gate 证据。

## 5. 尚未关闭

- G9D–G9G 尚未实现；
- honest 300 public chain 的 completed-resume 仍需在最终 integration test revision 上重跑；
- 当前 example config 的 `meta.enabled=false` 会使真实 G0 fail closed，这是配置/环境准入事实，不由 G9C
  静默放宽；
- Linux/ext4 与真实远端 tracking 仍开放，按用户当前目标暂不作为本轮阻断。
