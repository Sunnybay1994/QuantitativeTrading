# M3 G1-P4B 主验一次返工交付报告

日期：2026-07-15  
角色：原外部实现 Agent（非独立复验）  
实际模型标识：`cursor-grok-4.5-high`  
返工任务单：[`M3_G1_P4B主验一次返工任务单.md`](M3_G1_P4B主验一次返工任务单.md)  
独立复验：[`M3_G1_P4B独立初验一次返工独立复验报告.md`](M3_G1_P4B独立初验一次返工独立复验报告.md)  
前次返工交付：[`M3_G1_P4B独立初验一次返工交付报告.md`](M3_G1_P4B独立初验一次返工交付报告.md)  
状态：**待独立复验/待主验**（不得视为 B4 / G1 / M3 / Gate 通过）

## 1. 范围

仅修改：

- `src/quant/data/m3_reference.py`（`_derive_cross_source_from_detail` 缺侧语义 + bundle receipt digest 闭包）
- `tests/unit/test_m3_reference.py`（H1–H3 回归）
- 本报告

未改公共接口、connector、P4A、RawStore、其他测试、配置、路线图或历史报告。  
未扩大到任务单标明的非阻塞观察（`missing_primary` planner 可达性、raw symlink 错误码）。

## 2. H1：缺侧 detail tolerance 必须 exact `0.0`

| 项 | 内容 |
|---|---|
| 现象 | 真实 `missing_side="REFERENCE"` 五格把 `tolerance` 改为 `123.0` 并重绑 detail/summary hash 后，bundle 仍构造成功 |
| 根因 | shared helper 对缺侧只要求 tolerance finite/nonnegative，未锁定生产 canonical `0.0` |
| 规则 | 原任务书 §7.6/§7.8 与 F1：缺侧固定 `abs_diff=None`、`relative_diff=None`、`tolerance=0.0`、`matched=False`；不得允许多个 hash 不同的自洽表示 |
| 最小复现 | 主验临时 `test_main_hidden_missing_rows_require_fixed_zero_tolerance`（已删）；本轮 `test_h1_missing_rows_require_exact_zero_tolerance` |
| 修复 | `_derive_cross_source_from_detail` 缺侧分支改为 `type(tolerance) is float and math.isfinite(tolerance) and tolerance != 0.0` 必拒；`-0.0` 按 Python 数值相等接受 |
| 新增测试 | `test_h1_missing_rows_require_exact_zero_tolerance`：REFERENCE 真实缺行 + PRIMARY/BOTH 伪造缺行；覆盖 `123.0`/NaN/Inf/null/错误 dtype；`-0.0` 与 `0.0` 合法路径通过 |
| 通过条件 | 三类缺侧非法 tolerance 必拒；正常缺行/停牌与合法 `0.0`/`-0.0` 继续通过 |

## 3. H2：缺侧现存侧必须领域合法

| 项 | 内容 |
|---|---|
| 现象 | 缺 REFERENCE 时把现存 primary 五值改为 `-1.0` 并重绑 hash，bundle 仍构造成功 |
| 根因 | PRIMARY/REFERENCE 分支只验哪一侧为 null，未验另一侧 float/finite/价格正值/成交量非负 |
| 规则 | 现存侧必须 exact finite float；OHLC `> 0.0`，volume `>= 0.0`；BOTH 两侧均 null；异常稳定 `ValueError`，不泄露 raw |
| 最小复现 | 主验临时 `test_main_hidden_missing_rows_validate_the_present_side_domain_value`（已删）；本轮 `test_h2_missing_rows_reject_invalid_present_side_domain` |
| 修复 | 新增 `_validate_present_side_value`；PRIMARY 校验 `reference_value`，REFERENCE 校验 `primary_value`；BOTH 仍要求双侧 null |
| 新增测试 | `test_h2_missing_rows_reject_invalid_present_side_domain`（PRIMARY/REFERENCE × 价格 0/-1/NaN/Inf 与 volume -1/NaN/Inf）；`test_h2_missing_rows_accept_valid_present_side_and_both_nulls`（volume=0、正价、BOTH 合法/非法） |
| 通过条件 | 非法现存侧必拒且无路径/polars；合法正价与 volume=0、BOTH 双侧 null 通过 |

## 4. H3：30 receipts 的 `stable_response_sha256` 必须 30 唯一

| 项 | 内容 |
|---|---|
| 现象 | 保留 30 个唯一 `request_id`，把第二个 receipt 的 stable digest 改成第一个，同时把 summary digests 自洽压成 29，bundle 仍构造成功 |
| 根因 | 构造器只比较 `sorted(set(stable_response_sha256))`，未要求集合大小也为 30；前次反例未覆盖 receipt+summary 同漂移 |
| 规则 | 除密码学碰撞外，30 个不同 request 必须对应 30 个不同 stable response identity；summary digest tuple 长度必须为 30 且完全相等 |
| 最小复现 | 主验临时 `test_main_hidden_reference_stable_response_digests_remain_one_per_request`（已删）；本轮 `test_h3_stable_response_digests_remain_one_per_request` |
| 修复 | bundle：`len(set(stable_digests)) == 30`；`expected_ref_digests = tuple(sorted(stable_digests))`（长度 30）；另强制 `len(summary.reference_receipt_digests) == 30` |
| 新增测试 | `test_h3_stable_response_digests_remain_one_per_request`：仅 receipt 漂移、仅 summary 漂移、二者自洽同漂移三类必拒；正常 30 对 30 断言 |
| 通过条件 | 三类伪造必拒；happy path 仍为精确 30 receipts / 30 unique digests / summary 长度 30 |

## 5. 验证结果（WSL Miniforge `base`）

全部经 `wsl.exe` → `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant` → `/home/mabw/miniforge3/bin/conda run -n base`。

| 步骤 | 命令 | 结果 |
|---|---|---|
| 1 返工定向 | `pytest -q tests/unit/test_m3_reference.py -k "h1_ or h2_ or h3_ or adv5_ or adv9_ or f3_"` | **23 passed** |
| 2 P4B+connector | `pytest -q tests/unit/test_m3_reference.py tests/unit/test_baostock_connector.py` | **133 passed** |
| 3 P4A | `pytest -q tests/unit/test_m3_g1_candidate.py` | **33 passed** |
| 4 全量 | `pytest -q` | **769 passed** |
| 5 Ruff | `ruff check src tests` | **All checks passed** |
| 6 mypy | `mypy src` | **78 source files，0 issues** |

未联网、未读 token、未访问 `_old/`。未使用 Windows Python/conda 跑项目测试。

## 6. 交付声明

H1–H3 已按主验一次返工任务单最小修复并自测；状态：**待独立复验/待主验**。  
请未参与本轮返工的全新外部会话重放三个主验反例，并至少增加两个未使用变体（尤其缺 PRIMARY 与 30 digest 同漂移）。  
不宣称 B4 / G1 / M3 / 任一 Gate 通过。
