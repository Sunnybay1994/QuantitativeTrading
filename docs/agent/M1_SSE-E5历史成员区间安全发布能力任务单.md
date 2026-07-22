# M1 SSE-E5 历史成员区间安全发布能力任务单

## 1. 目标

升级现有 `rebuild_connect_universe`，使其可消费 E3/E4 verified reverse audit，并通过受控 store 发布单 route
`UniverseMembershipSchema`。本包只实现代码和 tmp/fake 测试，不运行项目真实 data 发布。

## 2. Store 合同

新增：

```python
CleanUniverseMembershipStore.replace_universe(frame: pl.DataFrame) -> int
```

- frame 非空、严格 Schema、恰一个 `universe` 且只允许 `SH_CONNECT/SZ_CONNECT`；
- 只替换 `root/universe=<route>/data.parquet`，不 concat；排序 `symbol,effective_from`；
- root/祖先/universe/target/temp symlink、FIFO、目录、非普通文件 fail-closed，外部文件不变；
- 写后重新读 Schema，并精确核对行数与 `(universe,symbol,effective_from,effective_to)` 集合；
- 另一 universe bytes/mtime 不变；重复发布确定幂等。

旧 `replace` 保持兼容，不在本包自动迁移其他调用方。

## 3. CLI 合同

`rebuild_connect_universe` 增加：

- `--mode snapshot|reverse-audit`，默认 `snapshot` 保持现有语义；
- `--snapshot-date`、`--expected-baseline-count`：仅 reverse-audit 必需，snapshot mode 禁止；
- `--dry-run`：两模式均可，构建/验证但不写 universe。

所有模式使用 `CleanConnectSnapshotStore.read_route_date` 和 `CleanConnectEventStore.read_route`，禁止直接
`pl.read_parquet`、自动发现或读取 legacy。

reverse-audit 模式必须依次：

1. `verify_reverse_eligibility_history`
2. `build_membership_intervals_from_reverse_audit`
3. dry-run 返回，或 `replace_universe`

严格参数关系在任何 FS 写入前拒绝。成功单行 JSON：`route/mode/baseline_date/snapshot_date/rows/symbols/
coverage_start/open_intervals/published/status`，不得输出 symbol 全集或物理路径。失败非零且无伪成功 JSON。

## 4. 文件白名单

- `src/quant/data/storage.py`
- `src/quant/data/rebuild_connect_universe.py`
- `tests/unit/test_storage.py`
- `tests/unit/test_rebuild_connect_universe.py`（现有或新）
- `README.md`
- `docs/agent/M1_SSE-E5历史成员区间安全发布能力交付报告.md`

## 5. 必测反例与验证

- reverse SH/SZ fake 正常 dry-run/发布，结果与 E4 preview 一致；snapshot 旧命令兼容；
- reverse 参数缺失/多余、bool/int、datetime/date、非法 mode/route 在写前失败；
- dry-run 前后 universe bytes/mtime 不变；发布只改目标 route；
- forged/mixed snapshot/events 由 E3/E4 拒绝；不得绕过 verified builder；
- universe root/祖先/route/target/temp symlink、FIFO/目录攻击 fail-closed；
- 写后校验失败不打印 published=true；重复发布无重复；
- `/tmp` 初验反例：目标 route 合法但 sibling route 是 symlink 指向外部，发布目标 route 不得触碰 sibling，
  且外部 bytes/mtime 不变。

WSL Miniforge base：

```bash
python -m pytest tests/unit/test_storage.py -q -k 'universe and (replace or publish)'
python -m pytest tests/unit/test_rebuild_connect_universe.py -q
ruff check src/quant/data/storage.py src/quant/data/rebuild_connect_universe.py tests/unit/test_storage.py tests/unit/test_rebuild_connect_universe.py
mypy src/quant/data/storage.py src/quant/data/rebuild_connect_universe.py
```

禁止网络、项目真实 data、全量 pytest、Git。实现/独立初验使用不同全新 `cursor-grok-4.5-high`；初验除
唯一报告外代码只读。通过仅代表发布能力，不代表实际 universe 已发布。
