# M1 SSE-E4 逆向基线到成员区间 Preview 独立初验报告

日期：2026-07-17  
角色：外部独立初验 Agent（全新会话，未参与实现；模型 cursor-grok-4.5-high）  
任务单：[M1_SSE-E4逆向基线到成员区间Preview任务单.md](M1_SSE-E4逆向基线到成员区间Preview任务单.md)  
交付报告：[M1_SSE-E4逆向基线到成员区间Preview交付报告.md](M1_SSE-E4逆向基线到成员区间Preview交付报告.md)  
前置主验：[M1_SSE-E1港股通事件方向映射主Agent最终验收报告.md](M1_SSE-E1港股通事件方向映射主Agent最终验收报告.md)、[M1_SSE-E2单RouteClean事件原子重建主Agent最终验收报告.md](M1_SSE-E2单RouteClean事件原子重建主Agent最终验收报告.md)、[M1_SSE-E3历史资格逆向审计工具主Agent最终验收报告.md](M1_SSE-E3历史资格逆向审计工具主Agent最终验收报告.md)

**结论：初验通过（exit 0）。** 生产代码/实现测试/README/配置/data 严格只读；未联网、未访问项目 `data/`、未写 universe、未跑全量 pytest、未做 Git。不宣称真实历史覆盖已发布，不宣称 Gate 通过。

## 1. 范围与纪律

| 项 | 状态 |
|---|---|
| 唯一写入 | 本报告 |
| 生产代码/实现测试/README/配置 | 只读 |
| 项目 `data/` / 网络 / universe 写入 / 全量 pytest / Git | 未触碰 |
| 环境 | WSL Miniforge `base`（`/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`） |
| 对抗工作区 | `/tmp/m1_sse_e4_adversarial.py` |

## 2. 合同逐项核对

| # | 冻结合同点 | 证据 | 结论 |
|---|---|---|---|
| 1 | `audit` exact type；对 snapshot/events 重调 `verify_reverse_eligibility_history`，逐字段精确等于传入 audit；`__setattr__`/跨批拒绝 | `eligibility.py` exact type 检查；recompute + `_audit_fields_equal` 十字段比对；单测 forged/跨批 + `/tmp` A2/X1/X2 | 通过 |
| 2 | verified `baseline_symbols` 在 `baseline_date` 全员 active；按 `effective_date,symbol` 正序回放；ADD 仅入 inactive，REMOVE 仅关 active；区间止于 REMOVE 日前一自然日 | 回放循环；fixture REMOVE 2020-06-01 对应 `effective_to=2020-05-31`；多段 re-add 单测 | 通过 |
| 3 | 输出过 `UniverseMembershipSchema`，`universe=route`；同证券区间无重叠/倒置；最终 active 精确集合等于 snapshot symbols（非仅 count） | Schema.validate；重叠检查；`set(active) != snapshot_symbols` 拒绝；happy path + A1 同 count 换符拒绝 | 通过 |
| 4 | 不推断 baseline 前加入日；baseline symbol 首段 `effective_from=baseline_date`；基线前查询 fail-closed | 首段断言单测；`eligible_symbols_on` 早于覆盖起点抛错 | 通过 |
| 5 | 稳定脱敏码：INPUT_INVALID / AUDIT_MISMATCH / STATE_CONFLICT / FINAL_STATE_MISMATCH；不回声 symbol/path | 错误码 frozenset；错误串单测 + `/tmp` forbid_echo 全过 | 通过 |
| 6 | CLI `--preview-membership`：仅 audit PASS 后追加四字段；无 symbol 全集/path；不写文件；未指定 flag 时默认 JSON 字段精确不变；bytes/mtime 不变 | CLI 实现与默认/preview 单测；readonly mtime 断言 | 通过 |
| 7 | 白名单外无 universe 写入；`quant.data` 安全导出；README 说明 preview 只读 | `__init__.py` 导出；README 明确不写；preview 路径无 universe upsert/replace | 通过 |

## 3. 定向验证（任务单三项）

```text
python -m pytest tests/unit/test_eligibility.py tests/unit/test_audit_connect_eligibility.py -q
  → 30 passed                 exit 0

ruff check src/quant/data/eligibility.py src/quant/data/audit_connect_eligibility.py \
  tests/unit/test_eligibility.py tests/unit/test_audit_connect_eligibility.py
  → All checks passed!        exit 0

mypy src/quant/data/eligibility.py src/quant/data/audit_connect_eligibility.py
  → Success: no issues found in 2 source files   exit 0
```

合计：`EXITS pytest=0 ruff=0 mypy=0 adv=0`。

## 4. 实现者未公开对抗（WSL `/tmp`）

相对交付报告与实现单测（其 fixture 为 `0000x.HK` / 2020-2021），本初验使用独立 fixture `0070x.HK` / 2019-2022，含多段 REMOVE 再 ADD 与临时 ADD 再 REMOVE：

| ID | 反例 | 期望 | 结果 |
|---|---|---|---|
| A1 | snapshot 将 `00703.HK` 换成 `00777.HK`，height/count 不变 | AUDIT_MISMATCH 或 FINAL_STATE_MISMATCH；不得按 count 放行；无 symbol 回声 | PASS → `REVERSE_MEMBERSHIP_AUDIT_MISMATCH` |
| A2 | `object.__setattr__` 伪造 `baseline_symbols` 为两只新 symbol，长度(=count)不变 | 同上 | PASS → `REVERSE_MEMBERSHIP_AUDIT_MISMATCH` |
| A3 | events 少一行 | 同上 | PASS → `REVERSE_MEMBERSHIP_AUDIT_MISMATCH` |
| A4 | events 多一行（追加 ADD） | 同上 | PASS → `REVERSE_MEMBERSHIP_AUDIT_MISMATCH` |
| X1 | 伪造 `event_count+1`（交付建议补充） | AUDIT_MISMATCH | PASS → `REVERSE_MEMBERSHIP_AUDIT_MISMATCH` |
| X2 | 伪造 `snapshot_date` 仍配原 snapshot | AUDIT_MISMATCH | PASS → `REVERSE_MEMBERSHIP_AUDIT_MISMATCH` |

```text
PASS happy_path_final_set_exact
A1-A4 / X1-X2 PASS
ALL_ADVERSARIAL_PASS  exit 0
```

说明：A1 在重验 `verify_reverse_eligibility_history` 阶段即 AUDIT_MISMATCH（换符后 reverse/current 集合漂移），属合同允许的更早安全层，未走到仅比 count 的放行路径。

## 5. 已知非阻塞备注（不构成初验失败）

- 本包仅 preview 代码能力；真实 SH clean 若仍含旧 mapper 错误 action，真实 audit 仍可能 STATE_CONFLICT——属 E2 授权 replace 后事项，与 E3 主验一致。
- `eligible_symbols_on` 基线前失败文案仍含日期字面量（既有 API），membership 四码路径本身不回声 symbol/path。

## 6. 初验判定

- **初验：通过**
- **综合退出码：0**
- 返工项：无
- 下一步：交主 Agent 终验；不得由本报告勾选路线图或宣称 `clean/universe_membership` 已写入/历史覆盖已发布。
