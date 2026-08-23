# M1 SSE-E3 历史资格逆向审计工具任务单

## 1. 目标

提供零网络、只读、可重复的 `quant.data` 审计入口，用指定 current snapshot 和完整事件流逆向回放到官方启动
基线。它只产生严格 JSON 结果，不发布 snapshot/universe，不直接修改 data。

## 2. 领域合同

新增 frozen/slots 值对象 `VerifiedReverseEligibilityAudit` 与纯函数：

```python
verify_reverse_eligibility_history(
    snapshot: pl.DataFrame,
    events: pl.DataFrame,
    *,
    route: str,
    baseline_date: dt.date,
    expected_baseline_count: int,
) -> VerifiedReverseEligibilityAudit
```

要求：

1. 输入先过 `ConnectEligibilitySnapshotSchema` / `ConnectEligibilityEventSchema`；route 只允许领域已有
   `SH_CONNECT/SZ_CONNECT`，baseline_date 必须 exact date，expected count 严格正 int。
2. snapshot 必须恰一个 route、一个 snapshot_date，且全部 `buy_eligible=True`；snapshot_date > baseline_date。
3. events 必须恰含该 route，全部满足 `baseline_date < effective_date <= snapshot_date`；同日同证券重复或同时
   ADD/REMOVE 拒绝。
4. 从 snapshot active set 按 `effective_date,symbol` 逆序：逆 ADD 要求证券当前 active 后删除；逆 REMOVE
   要求当前 inactive 后加入。任一状态矛盾 fail-closed。
5. 最终集合大小必须等于 expected count；返回排序后的 `baseline_symbols`、current/event/reverse counts、
   first/last event dates。值对象构造时重算上述不变量，调用者不得自报成功。
6. 稳定错误统一 `EligibilityHistoryError`，信息用固定 code，不回声 symbol/path/raw 值：
   `REVERSE_AUDIT_INPUT_INVALID`、`REVERSE_AUDIT_COVERAGE_INVALID`、`REVERSE_AUDIT_EVENT_CONFLICT`、
   `REVERSE_AUDIT_STATE_CONFLICT`、`REVERSE_AUDIT_COUNT_MISMATCH`。

## 3. Repository 与 CLI

1. 在 `quant.data.storage` 增加显式只读 reader：
   - `CleanConnectSnapshotStore.read_route_date(*, route, snapshot_date)`
   - `CleanConnectEventStore.read_route(*, route)`
2. reader 只打开精确路径，不做全盘/legacy 自动发现；目标、route/date 目录或其受控祖先为 symlink、非普通
   文件、缺失、Schema 非法时稳定失败，不跟随外部路径。
3. 新 CLI：

```bash
python -m quant.data.audit_connect_eligibility \
  --route SH_CONNECT --snapshot-date 2026-07-10 \
  --baseline-date 2014-11-17 --expected-baseline-count 268
```

默认 `--data-root data`；严格参数。成功输出单行严格 JSON，含 route/dates/counts/event_min/event_max/status=PASS；
失败非零且不得输出 baseline_symbols 全集、路径或数据内容。CLI 只读，不联网、不写 artifact。

## 4. 文件白名单

- `src/quant/data/eligibility.py`
- `src/quant/data/storage.py`
- `src/quant/data/audit_connect_eligibility.py`（新）
- `src/quant/data/__init__.py`（仅安全导出值对象/纯函数）
- `tests/unit/test_eligibility.py`
- `tests/unit/test_storage.py`
- `tests/unit/test_audit_connect_eligibility.py`（新）
- `README.md`（只读审计命令）
- `docs/framework/agent/M1_SSE-E3历史资格逆向审计工具交付报告.md`

## 5. 必测反例与验证

- SH fixture 逆推 268、SZ fixture 逆推 417；输入行序变化结果一致；
- reverse ADD 缺 active、reverse REMOVE 已 active、同日同证券冲突、count mismatch、越界事件全部对应稳定码；
- bool/int、datetime/date、非法 route 严格拒绝；异常不含 symbol/path；
- reader 的 root/祖先/route/date/target symlink、FIFO、目录、缺失均 fail-closed；
- CLI 成功 JSON 不含 symbols/path；失败无 stdout 成功 JSON；data 字节/mtime 前后不变；
- 禁止网络、项目真实 data、全量 pytest、Git。

WSL Miniforge base：

```bash
python -m pytest tests/unit/test_eligibility.py tests/unit/test_audit_connect_eligibility.py -q
python -m pytest tests/unit/test_storage.py -q -k 'connect and read'
ruff check src/quant/data/eligibility.py src/quant/data/storage.py src/quant/data/audit_connect_eligibility.py tests/unit/test_eligibility.py tests/unit/test_storage.py tests/unit/test_audit_connect_eligibility.py
mypy src/quant/data/eligibility.py src/quant/data/storage.py src/quant/data/audit_connect_eligibility.py
```

实现/独立初验使用不同全新 `cursor-grok-4.5-high`。初验除唯一报告外代码只读，须补“完整合法事件集合中
插入一个早于 baseline 的事件不得被静默过滤”的 `/tmp` 反例。
