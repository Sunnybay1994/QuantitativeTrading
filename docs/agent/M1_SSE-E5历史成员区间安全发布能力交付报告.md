# M1 SSE-E5 历史成员区间安全发布能力交付报告

日期：2026-07-17  
角色：外部实现 Agent（cursor-grok-4.5-high）  
任务单：[M1_SSE-E5历史成员区间安全发布能力任务单.md](M1_SSE-E5历史成员区间安全发布能力任务单.md)  
结论：**实现自测完成，待独立初验与主验；未宣称 Gate 通过；未发布历史 universe**

## 1. 完成内容

- 新增 `CleanUniverseMembershipStore.replace_universe`：非空、严格 Schema、恰一个
  `universe` 且仅 `SH_CONNECT/SZ_CONNECT`；排序 `symbol,effective_from`；经
  `_replace_parquet_guarded` 原子替换；写后重读 Schema 并精确核对行数与
  `(universe,symbol,effective_from,effective_to)` 集合。旧 `replace` 保持兼容。
- 升级 `rebuild_connect_universe`：`--mode snapshot|reverse-audit`（默认 snapshot）、
  reverse 专用 `--snapshot-date`/`--expected-baseline-count`、两模式可用 `--dry-run`。
  全部经 `CleanConnectSnapshotStore.read_route_date` 与 `CleanConnectEventStore.read_route`，
  禁止直接 `pl.read_parquet` / 自动发现 / legacy。
- reverse-audit 依次：`verify_reverse_eligibility_history` →
  `build_membership_intervals_from_reverse_audit` → dry-run 返回或 `replace_universe`。
- 严格参数关系在任何 FS 写入前拒绝；成功单行 JSON 字段为
  `route/mode/baseline_date/snapshot_date/rows/symbols/coverage_start/open_intervals/published/status`，
  不含 symbol 全集或物理路径；失败非零且无伪成功 JSON。
- 路径攻击 fail-closed（root/祖先/universe/target/temp symlink、FIFO、目录）；sibling
  symlink 指向外部时发布目标 route 不触碰 sibling，外部 bytes/mtime 不变。

## 2. 白名单改动文件

| 文件 | 目的 |
|---|---|
| `src/quant/data/storage.py` | `replace_universe` 受控单 universe 发布 |
| `src/quant/data/rebuild_connect_universe.py` | reverse-audit/dry-run 与 snapshot 兼容 CLI |
| `tests/unit/test_storage.py` | universe replace 幂等/隔离/路径攻击 |
| `tests/unit/test_rebuild_connect_universe.py` | CLI dry-run/发布/参数/反例（新建） |
| `README.md` | reverse-audit / dry-run 命令与 JSON 合同说明 |
| `docs/agent/M1_SSE-E5历史成员区间安全发布能力交付报告.md` | 本报告 |

未改 eligibility / audit CLI / Schema / enums；未触达项目真实 `data/`；未联网、未全量 pytest、未 Git。

## 3. 验证（WSL Miniforge base，tmp/fake）

```text
python -m pytest tests/unit/test_storage.py -q -k 'universe and (replace or publish)'
→ 10 passed, 29 deselected；退出码 0

python -m pytest tests/unit/test_rebuild_connect_universe.py -q
→ 12 passed；退出码 0

ruff check src/quant/data/storage.py src/quant/data/rebuild_connect_universe.py \
  tests/unit/test_storage.py tests/unit/test_rebuild_connect_universe.py
→ All checks passed!；退出码 0

mypy src/quant/data/storage.py src/quant/data/rebuild_connect_universe.py
→ Success: no issues found in 2 source files；退出码 0
```

覆盖：SH/SZ reverse dry-run/发布与 E4 preview 一致、snapshot 旧命令兼容、参数缺失/多余/
bool/int/datetime fail-closed、dry-run bytes/mtime 不变、仅改目标 route、forged 事件拒绝、
重复发布幂等、target/祖先/root/temp symlink 与 FIFO/目录攻击、sibling symlink 外部不变。

## 4. 明确非宣称

- 不宣称 M1 Gate / SSE-E5 最终通过。
- 不宣称历史 universe / baseline 已发布，或项目 `clean/universe_membership` 已写入。
- 本包仅发布**能力**；真实 SH clean 仍须先完成 E2 授权 replace，再经独立授权后才可对真实 data 发布。

## 5. 风险与下一步

- 现有项目 SH clean 若仍含旧 mapper 错误 action，真实 reverse-audit 仍可能 STATE_CONFLICT；
  本 CLI 不会绕过 E3/E4 门禁。
- 独立初验须只读核对，并补实现者未用的对抗性反例（任务单建议：`/tmp` sibling symlink +
  写后校验失败不打印 `published=true`）。
- 初验通过后由主 Agent 终验；实现者不得自行勾选路线图或宣布历史覆盖已发布。
