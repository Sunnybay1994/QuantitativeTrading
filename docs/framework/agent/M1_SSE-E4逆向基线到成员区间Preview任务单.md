# M1 SSE-E4 逆向基线到成员区间 Preview 任务单

## 1. 目标

将 E3 的 verified reverse baseline 转成严格 `UniverseMembershipSchema` 区间，但必须重新绑定原 snapshot 和
events，防止伪造 audit 或跨批混配。本包只 preview，不写 `clean/universe_membership`。

## 2. 冻结接口

```python
build_membership_intervals_from_reverse_audit(
    *,
    audit: VerifiedReverseEligibilityAudit,
    snapshot: pl.DataFrame,
    events: pl.DataFrame,
) -> pl.DataFrame
```

1. `audit` 必须 exact type；先以 audit 中 route/baseline/expected count 对 snapshot/events 重新调用
   `verify_reverse_eligibility_history`，并逐字段精确等于传入 audit。object.__setattr__ 篡改或跨批 audit 拒绝。
2. 以 verified `baseline_symbols` 在 `baseline_date` 全部 active，按 `effective_date,symbol` 正序回放完整 events：
   ADD 只能加入 inactive，REMOVE 只能关闭 active；区间结束为 REMOVE 生效日前一自然日。
3. 输出过 `UniverseMembershipSchema`，`universe=route`；同证券区间不得重叠/倒置；最后 active symbol 集合必须
   精确等于 snapshot symbol 集合，而不只比较 count。
4. 不推断 baseline 前加入日；所有 baseline symbol 的首段 `effective_from=baseline_date`。
5. 稳定脱敏错误码：`REVERSE_MEMBERSHIP_INPUT_INVALID`、`REVERSE_MEMBERSHIP_AUDIT_MISMATCH`、
   `REVERSE_MEMBERSHIP_STATE_CONFLICT`、`REVERSE_MEMBERSHIP_FINAL_STATE_MISMATCH`。不得回声 symbol/path。

## 3. Preview CLI

在现有 `quant.data.audit_connect_eligibility` 增加 `--preview-membership`。只有 audit PASS 后构建 preview；成功
JSON 追加：

- `membership_rows`
- `membership_symbols`
- `coverage_start`
- `open_intervals`

不得输出 symbol 全集、物理路径或写任何文件。未指定 flag 时现有 JSON 精确字段不变。失败非零、无伪成功 JSON。

## 4. 文件白名单

- `src/quant/data/eligibility.py`
- `src/quant/data/audit_connect_eligibility.py`
- `src/quant/data/__init__.py`
- `tests/unit/test_eligibility.py`
- `tests/unit/test_audit_connect_eligibility.py`
- `README.md`
- `docs/framework/agent/M1_SSE-E4逆向基线到成员区间Preview交付报告.md`

## 5. 反例与验证

- 小型 SH/SZ fixture 的 preview 区间、remove 前一日、重新 add、多段区间、最终 active 精确闭合；
- 行序变化结果确定；
- forged audit、另一 snapshot 的 audit、事件少一行/多一行、同 count 不同 symbol 最终集合全部拒绝；
- baseline symbol 首段日期正确，baseline 前查询仍由现有 API fail-closed；
- CLI flag 成功字段正确且无 symbols/path，默认 JSON 不变，运行前后 tmp data bytes/mtime 不变；
- `/tmp` 独立反例：把 snapshot 中一个 symbol 换成另一个、维持相同 count，必须 FINAL_STATE_MISMATCH 或更早
  AUDIT_MISMATCH，不得按 count 放行。

WSL Miniforge base：

```bash
python -m pytest tests/unit/test_eligibility.py tests/unit/test_audit_connect_eligibility.py -q
ruff check src/quant/data/eligibility.py src/quant/data/audit_connect_eligibility.py tests/unit/test_eligibility.py tests/unit/test_audit_connect_eligibility.py
mypy src/quant/data/eligibility.py src/quant/data/audit_connect_eligibility.py
```

禁止网络、项目真实 data、universe 写入、全量 pytest、Git。实现/独立初验使用不同全新
`cursor-grok-4.5-high`；初验除唯一报告外代码只读。
