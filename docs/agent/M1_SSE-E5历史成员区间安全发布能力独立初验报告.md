# M1 SSE-E5 历史成员区间安全发布能力独立初验报告

日期：2026-07-17  
角色：外部独立初验 Agent（全新会话，未参与实现；模型 cursor-grok-4.5-high）  
任务单：[M1_SSE-E5历史成员区间安全发布能力任务单.md](M1_SSE-E5历史成员区间安全发布能力任务单.md)  
交付报告：[M1_SSE-E5历史成员区间安全发布能力交付报告.md](M1_SSE-E5历史成员区间安全发布能力交付报告.md)  
前置主验：[M1_SSE-E1港股通事件方向映射主Agent最终验收报告.md](M1_SSE-E1港股通事件方向映射主Agent最终验收报告.md)、[M1_SSE-E2单RouteClean事件原子重建主Agent最终验收报告.md](M1_SSE-E2单RouteClean事件原子重建主Agent最终验收报告.md)、[M1_SSE-E3历史资格逆向审计工具主Agent最终验收报告.md](M1_SSE-E3历史资格逆向审计工具主Agent最终验收报告.md)、[M1_SSE-E4逆向基线到成员区间Preview主Agent最终验收报告.md](M1_SSE-E4逆向基线到成员区间Preview主Agent最终验收报告.md)

**结论：初验通过（exit 0）。** 生产代码/实现测试/README/配置/data 严格只读；唯一写入为本报告。未联网、未访问项目 `data/`、未真实发布 universe、未跑全量 pytest、未做 Git。不宣称历史 universe 已发布，不宣称 Gate 通过。

## 1. 范围与纪律

| 项 | 状态 |
|---|---|
| 唯一写入 | 本报告 |
| 生产代码 / 实现测试 / README / 配置 | 只读 |
| 项目 `data/` / 网络 / 真实发布 / 全量 pytest / Git | 未触碰 |
| 环境 | WSL Miniforge `base`（`/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`） |
| 对抗工作区 | `/tmp/sse_e5_adv_verify.py`（原生 Linux `/tmp`，非项目目录） |

## 2. 合同逐项核对

| # | 冻结合同点 | 证据 | 结论 |
|---|---|---|---|
| 1 | `replace_universe`：非空、严格 Schema、恰一个 `universe` 且仅 `SH_CONNECT/SZ_CONNECT`；排序 `symbol,effective_from`；不 concat；经 `_replace_parquet_guarded` | `storage.py` `CleanUniverseMembershipStore.replace_universe`；单测 empty/multi/illegal/幂等 | 通过 |
| 2 | 写后重读 Schema，精确核对行数与 `(universe,symbol,effective_from,effective_to)` 集合 | `replace_universe` 写后校验块；失败抛 `ValueError("replace_universe 写后校验失败")` | 通过 |
| 3 | 另一 universe bytes/mtime 不变；重复发布确定幂等；旧 `replace` 保持兼容 | `test_universe_replace_leaves_other_universe_*`、`drops_old_and_is_deterministic`；旧 `replace` 仍走 `_replace_parquet` | 通过 |
| 4 | root/祖先/universe/target/temp symlink、FIFO、目录、非普通文件 fail-closed；外部不变 | storage 单测 + `/tmp` ADV3/ADV5 | 通过 |
| 5 | CLI `--mode snapshot\|reverse-audit`（默认 snapshot）；reverse 必需 `--snapshot-date`/`--expected-baseline-count`；snapshot 禁止二者；`--dry-run` 两模式可用 | `rebuild_connect_universe.py` `_validate_mode_args`；参数缺失/多余单测 | 通过 |
| 6 | 全部经 `CleanConnectSnapshotStore.read_route_date` / `CleanConnectEventStore.read_route`；禁止直接 `pl.read_parquet`、自动发现、legacy | CLI 源码无 `pl.read_parquet`/`legacy`/`glob`；仅显式 store | 通过 |
| 7 | reverse-audit 依次：`verify_reverse_eligibility_history` → `build_membership_intervals_from_reverse_audit` → dry-run 返回或 `replace_universe` | CLI `main` 分支顺序；与 E4 preview 一致单测 | 通过 |
| 8 | 严格参数（bool/int/datetime/date/非法 mode/route）在任何 FS 写入前拒绝 | `_validate_mode_args` 在 store 写入前；程序化 bool/int/datetime 单测；argparse 拒绝非法 mode/route | 通过 |
| 9 | 成功单行 JSON：`route/mode/baseline_date/snapshot_date/rows/symbols/coverage_start/open_intervals/published/status`；无 symbol 全集/物理路径；失败非零且无伪成功 JSON | `_success_payload` + `_assert_success_json`；路径攻击/forged/写后故障 stdout 为空 | 通过 |
| 10 | dry-run 前后 universe bytes/mtime 不变；发布只改目标 route；sibling 外部 symlink 不触碰 | dry-run/只改目标单测 + `/tmp` ADV1/ADV4 | 通过 |
| 11 | 写后校验失败不得输出 `published=true` | CLI：`published=True` 仅在 `replace_universe` 成功返回后；`/tmp` ADV2 故障注入 | 通过 |
| 12 | README 说明 reverse-audit/dry-run/JSON 合同；明确未经授权不对真实 data 发布 | README §港股通重建命令与说明 | 通过 |

## 3. 定向验证（任务单四项）

```text
python -m pytest tests/unit/test_storage.py -q -k 'universe and (replace or publish)'
  → 10 passed, 29 deselected                 exit 0

python -m pytest tests/unit/test_rebuild_connect_universe.py -q
  → 12 passed                                exit 0

ruff check src/quant/data/storage.py src/quant/data/rebuild_connect_universe.py \
  tests/unit/test_storage.py tests/unit/test_rebuild_connect_universe.py
  → All checks passed!                       exit 0

mypy src/quant/data/storage.py src/quant/data/rebuild_connect_universe.py
  → Success: no issues found in 2 source files   exit 0
```

合计：`EXITS pytest_storage=0 pytest_rebuild=0 ruff=0 mypy=0 adv=0`。

## 4. 实现者未公开对抗（WSL `/tmp`）

相对交付报告已列 sibling/路径攻击单测，本初验在原生 `/tmp` 另跑独立脚本（`/tmp/sse_e5_adv_verify.py`），并增加实现者未覆盖的**写后校验故障注入**与 **CLI FIFO 无伪成功 JSON**、**dry-run+sibling** 组合：

| ID | 反例 | 期望 | 结果 |
|---|---|---|---|
| ADV1 | 发布 SH 时 sibling `universe=SZ_CONNECT` 为指向外部的目录 symlink；store + CLI | SH 写入成功；外部 bytes/mtime 与 sibling link mtime 不变 | PASS |
| ADV2 | （未公开）写成功后注入 `replace_universe 写后校验失败`；另用 `pl.read_parquet` 返回空 frame 触发真实校验分支 | exit 1；stdout 空；不得出现 `published` | PASS |
| ADV3 | target symlink / temp symlink / FIFO / 目录目标 / ancestor symlink / root symlink | fail-closed；外部 marker 不变 | PASS（6/6） |
| ADV4 | （未公开）dry-run + sibling 外部 symlink | `published=false`；不创建 SH parquet；外部 bytes/mtime 不变 | PASS |
| ADV5 | （未公开）CLI 目标为 FIFO | exit 1；无成功 JSON/`published`；FIFO 仍在 | PASS → `clean 替换目标必须是普通文件` |

```text
WORK=/tmp/sse_e5_adv_*
pass=5 fail=0 total=5
ALL_ADVERSARIAL_PASS  exit 0
```

## 5. 已知非阻塞备注（不构成初验失败）

- 写后校验失败时，受控写入可能已落盘但 CLI 不以 `published=true` 宣称成功——符合任务单 JSON 合同；真实发布前仍须独立核对落盘内容。
- 本包仅发布**能力**；真实 SH clean 若仍含旧 mapper 错误 action，真实 reverse-audit 仍可能 `STATE_CONFLICT`（与 E1–E4 主验一致）。未经授权不得对项目 `data/` 执行发布。
- 旧 `replace` 仍为无 symlink 防护的兼容路径；新发布路径必须走 `replace_universe`。

## 6. 初验判定

- **初验：通过**
- **综合退出码：0**
- 返工项：无
- 下一步：交主 Agent 终验；不得由本报告勾选路线图或宣称 `clean/universe_membership` 已写入/历史覆盖已发布。
