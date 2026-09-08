# M1 SSE-E1 港股通事件方向映射修复 — 交付报告

日期：2026-07-17  
角色：外部实现 Agent（`cursor-grok-4.5-high`）  
合同：[`M1_SSE-E1港股通事件方向映射修复任务单.md`](M1_SSE-E1港股通事件方向映射修复任务单.md)  
状态：**已交付，待独立初验**（不宣称现有 clean 数据或 M1 Gate 已修复）

## 结果

- 状态：已交付
- `map_sse_events` 仅接受去空白后的官方中文「调进」→`ADD`、「调出」→`REMOVE`；
  null / 空串 / `"01"` / `"02"` / 英文 ADD·REMOVE / 未知中文在返回 DataFrame 前以
  稳定脱敏 `ValueError("SSE_EVENT_ADJUST_TYPE_INVALID")` 整批拒绝，绝不默认 REMOVE。
- 测试改为真实中文 raw 值，覆盖 ADD/REMOVE、首尾空白、混合合法批，以及每种非法值；
  另含经 mapper（不绕过）的状态机回归：当前成员调出再调进 + 新成员调进→调出→调进。
- 明确未修改：`eligibility.py`、Schema、其他生产文件、data/raw/clean、路线图；
  未跑网络、未做 data 读写/迁移、未跑全量 pytest、未触碰 Git。

## 修改文件及目的

| 文件 | 目的 |
| --- | --- |
| `src/quant/data/connect_market.py` | 修复 SSE `ADJUST_TYPE` 映射与未知值整批拒绝 |
| `tests/unit/test_connect_market.py` | 真实中文契约/反例 + mapper 状态机回归 |
| `docs/framework/agent/M1_SSE-E1港股通事件方向映射修复交付报告.md` | 本报告 |

## 设计与合同证据

| 成功标准 | 实现 / 测试证据 |
| --- | --- |
| 「调进」→ADD、「调出」→REMOVE | `map_sse_events`；`test_sse_event_mapping_add_and_remove` |
| 去首尾空白后识别 | `str.strip_chars()`；`test_sse_event_mapping_strips_whitespace` |
| 混合合法批可映射 | `test_sse_event_mapping_mixed_legal_batch` |
| null/空/`01`/`02`/英文/未知中文整批拒绝 | 返回前校验；parametrize + 混批含 `01` 反例 |
| 错误码稳定脱敏、不默认 REMOVE | 仅抛 `SSE_EVENT_ADJUST_TYPE_INVALID`，无 raw 值入消息 |
| 其他字段/route/source/security_type/published_date 不变 | select 列集未改；Schema 校验仍通过 |
| 状态机经 mapper，不改 eligibility | `test_sse_event_state_machine_add_remove_readd_via_mapper` |

与任务书无偏离。未宣称既有 clean 事件或 M1 Gate 已修复。

## 验证

环境：WSL `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，`/home/mabw/miniforge3/bin/conda run -n base`。

| 命令或检查 | 结果 | 证据 |
| --- | --- | --- |
| `python -m pytest tests/unit/test_connect_market.py -q` | 通过 | `17 passed`，EXIT `0` |
| `python -m pytest tests/unit/test_eligibility.py -q` | 通过 | `4 passed`，EXIT `0` |
| `ruff check src/quant/data/connect_market.py tests/unit/test_connect_market.py` | 通过 | `All checks passed!`，EXIT `0` |
| `mypy src/quant/data/connect_market.py` | 通过 | `Success: no issues found in 1 source file`，EXIT `0` |
| 全量 pytest / 网络 / data 迁移 | 未运行 | 任务书禁止 |

## 清理与范围审查

- 无临时代码；无第二套映射表；未改 SZSE mapper。
- 范围外改动：无。
- 文档：仅本交付报告。

## 风险与交接

- **已知限制**：本包只修零网络 mapper/测试；磁盘上既有 clean 事件仍可能全为错误 REMOVE，
  需后续单独授权 raw 保留、clean 原子重建与历史区间再发布。
- **未验证**：独立初验「合法与未知值同批」`/tmp` 反例；真实 SSE 端点再抓取；M1 Gate 终验。
- **下一步**：未参与实现的外部初验 Agent 只读核对，并写入
  `docs/framework/agent/M1_SSE-E1港股通事件方向映射修复独立初验报告.md`；主 Agent 终验前不得宣称
  M1 Gate / 现有 clean 已修复。
