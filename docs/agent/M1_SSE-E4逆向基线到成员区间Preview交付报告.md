# M1 SSE-E4 逆向基线到成员区间 Preview 交付报告

日期：2026-07-17  
角色：外部实现 Agent（cursor-grok-4.5-high）  
任务单：[M1_SSE-E4逆向基线到成员区间Preview任务单.md](M1_SSE-E4逆向基线到成员区间Preview任务单.md)  
结论：**实现自测完成，待独立初验与主验；未宣称 Gate 通过；未发布历史 universe**

## 1. 完成内容

- 新增纯函数 `build_membership_intervals_from_reverse_audit`：要求 `audit` exact type，
  以 audit 的 route/baseline/expected count 对传入 snapshot/events 重新调用
  `verify_reverse_eligibility_history`，并逐字段精确等于传入 audit；伪造
  `object.__setattr__` 或跨批 audit 拒绝。
- 以 verified `baseline_symbols` 在 `baseline_date` 全员 active，按
  `effective_date,symbol` 正序回放；ADD 仅入 inactive，REMOVE 仅关 active，区间止于
  REMOVE 生效日前一自然日；输出过 `UniverseMembershipSchema`，`universe=route`。
- 最终 active **精确集合相等**于 snapshot symbol 集合（非仅 count）；同证券区间无重叠/倒置。
- 稳定脱敏错误码：`REVERSE_MEMBERSHIP_INPUT_INVALID` /
  `AUDIT_MISMATCH` / `STATE_CONFLICT` / `FINAL_STATE_MISMATCH`，不回声 symbol/path。
- CLI 增加只读 `--preview-membership`：仅 audit PASS 后追加
  `membership_rows` / `membership_symbols` / `coverage_start` / `open_intervals`；
  无 symbol 全集、无路径、不写文件；未指定 flag 时默认 JSON 字段精确不变。
- `quant.data` 安全导出该纯函数；README 补充 preview 说明。

## 2. 白名单改动文件

| 文件 | 目的 |
|---|---|
| `src/quant/data/eligibility.py` | membership preview 纯函数与错误码 |
| `src/quant/data/audit_connect_eligibility.py` | `--preview-membership` 只读 flag |
| `src/quant/data/__init__.py` | 安全导出 |
| `tests/unit/test_eligibility.py` | preview 区间/反例/脱敏 |
| `tests/unit/test_audit_connect_eligibility.py` | CLI preview、默认 JSON、tmp 换符反例 |
| `README.md` | preview 命令说明 |
| `docs/agent/M1_SSE-E4逆向基线到成员区间Preview交付报告.md` | 本报告 |

未改 storage / rebuild CLI / Schema / enums；未触达项目真实 `data/`。

## 3. 验证（WSL Miniforge base，tmp/fake）

```text
python -m pytest tests/unit/test_eligibility.py tests/unit/test_audit_connect_eligibility.py -q
→ 30 passed；退出码 0

ruff check src/quant/data/eligibility.py src/quant/data/audit_connect_eligibility.py \
  tests/unit/test_eligibility.py tests/unit/test_audit_connect_eligibility.py
→ All checks passed!；退出码 0

mypy src/quant/data/eligibility.py src/quant/data/audit_connect_eligibility.py
→ Success: no issues found in 2 source files；退出码 0
```

覆盖：SH/SZ 小 fixture 多段区间与 remove 前一日、行序确定、forged/跨批 audit、事件少/多一行、
同 count 换 symbol（含独立 tmp 落盘反例）、baseline 首段日期与基线前 fail-closed、CLI 默认/
preview 字段与 bytes/mtime 不变。未联网、未全量 pytest、未 Git。

## 4. 明确非宣称

- 不宣称 M1 Gate / SSE-E4 最终通过。
- 不宣称历史 universe / baseline 已发布或 `clean/universe_membership` 已写入。
- 本包仅 preview 代码能力；真实 SH clean 仍须先完成 E2 授权 replace 后再做官方逆推与区间发布。

## 5. 风险与下一步

- 现有项目 SH clean 若仍含旧 mapper 错误 action，真实 audit 仍可能 STATE_CONFLICT；preview
  不会也不应绕过该门禁。
- 独立初验须只读核对，并补实现者未用的对抗性反例（建议再造：篡改 audit.event_count 或
  snapshot_date 后仍应 AUDIT_MISMATCH）。
- 初验通过后由主 Agent 终验；实现者不得自行勾选路线图或宣布历史覆盖已发布。
