# M3 G1-P2 B3：PIT 成员状态交付报告

日期：2026-07-14  
角色：外部实现 Agent（G1-P2 B3）  
实际模型标识：`cursor-grok-4.5-high`  
状态：**待独立初验**  
任务书：[`M3_G1_P2_B3PIT成员状态外部闭环任务单.md`](M3_G1_P2_B3PIT成员状态外部闭环任务单.md)

**本报告不宣称 B3 / P2 / G1 / Gate 完成。** 仅完成任务书冻结范围内的实现、实现者自测与本交付报告。

## 1. 修改文件

| 文件 | 改动 |
|---|---|
| `src/quant/data/index_membership.py` | **新增**：`M3IndexMembershipError`、`ObservedMembershipResult`、`normalize_index_weight_observations`、`build_observed_membership`、`verify_observed_membership_result` |
| `src/quant/data/m3_identity.py` | **新增**：`M3CleanTableIdentityError`、`clean_table_content_sha256`（`m3-clean-table-content-v1`） |
| `src/quant/domain/schemas.py` | **新增** `IndexConstituentObservationSchema`（字段 SSOT） |
| `src/quant/data/__init__.py` | 仅追加 B3 公开导出 |
| `src/quant/domain/__init__.py` | 仅追加 `IndexConstituentObservationSchema` 导出 |
| `tests/unit/test_index_membership.py` | **新增** 实现者测试（任务书 §11 矩阵） |
| `tests/unit/test_m3_identity.py` | **新增** clean digest 实现者测试 |
| `docs/M3_G1_P2_B3PIT成员状态交付报告.md` | 本交付报告 |

未修改：B2A/B2B 已验收生产代码、现有 fixture 期望、配置、路线图、Gate 状态；未启动 P3/P4；未读取 `_old/` 或 token 配置；未联网。

## 2. 冻结公共签名（实现核对）

```text
M3IndexMembershipError(code: str)  # str(error)==code；未知 code 拒绝
ObservedMembershipResult(
  observations, membership, eligible_keys,
  observations_sha256, membership_sha256, eligible_keys_sha256,
)  # frozen；构造时重验三表与三 digest

normalize_index_weight_observations(*, batch, responses, universe) -> pl.DataFrame
build_observed_membership(*, observations, calendars, instruments, universe,
  signal_start, signal_end, expected_constituent_count) -> ObservedMembershipResult
verify_observed_membership_result(*, batch, responses, result, calendars, instruments,
  universe, signal_start, signal_end, expected_constituent_count) -> None

M3CleanTableIdentityError(code: str)
clean_table_content_sha256(*, table_name, frame) -> str
IndexConstituentObservationSchema  # strict/coerce；唯一键 (universe,observation_date,symbol,source)
```

硬约束已落地：`universe` 仅 `CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1`；`source` 固定 `tushare`；指数代码固定 `000300.SH`；`expected_constituent_count` 必须精确为 `300`；方法语义为 observation 下一 SH session **收盘后** 可知（与 P2-0 `tushare_monthly_observed_next_session_close_v1` 一致）。

## 3. 实现要点（对照任务书不变量）

1. **请求闭包先于读值**：重建 `TushareRequestBatch` 与每个 `VerifiedRawResponse`；INDEX_WEIGHT、完整自然月、月份唯一连续、response request_id 多重集合与 batch 精确相等。
2. **PIT 三时点**：`observation_date` ← 供应商 `trade_date`；下一 SH session 收盘后形成 `as_of`；跨模块 fixture 固定 Friday→Monday `as_of`→Tuesday earliest open execution。
3. **300 / 权重和**：每 observation 恰 300 唯一 A 股；按 symbol 排序后 `math.fsum`，闭区间 `[99,101]`，不 round。
4. **membership / eligible_keys**：先生成状态区间，再与 signal window 与 instrument 生命周期相交；`effective_to` 一律非 null；持续成员合并、调出再入两段；每个 signal SH session 恰 300 资格键。
5. **verify**：从 batch/responses/calendar/instruments 重新 normalize+build，逐 frame/digest 比较；构造后 frame/hash 漂移与整套错移一天并同步改 digest 均失败。
6. **异常脱敏**：边界只抛稳定 code；`from None`；repr 不含路径/token/恶意输入。

## 4. 验证数字

环境：WSL Miniforge `base`，工作目录 `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，`PYTHONPATH=src`。未联网；未读取 token。

| 命令 | 结果 |
|---|---|
| `pytest -q tests/unit/test_index_membership.py tests/unit/test_m3_identity.py tests/unit/test_m3_backfill_requests.py tests/unit/test_m3_g1_mappers.py` | **166 passed** |
| `pytest -q`（全量） | **560 passed**（既有 Pandera/Polars deprecation warnings） |
| `ruff check src tests` | **All checks passed** |
| `mypy src` | **Success: no issues found in 75 source files** |
| B3 实现者测试数量 | `test_index_membership.py` **17** + `test_m3_identity.py` **6** = **23** |

Import 隔离：生产模块未引入 `qlib` / `mlflow` / `lightgbm` / `quant.research`；无网络/文件写入 API。

## 5. 未实现项 / 非本包范围

- B2C `stk_limit/dividend` mapper（P3）
- B4 candidate / 全局质量 / 跨源 / immutable release（P4）
- 真实 Tushare 网络抓取与 G1 release 终验
- 路线图勾选与任何 Gate 宣告

## 6. 契约疑问

无阻断性契约矛盾。说明性备注（不改变冻结行为）：

- 供应商 raw 中的 NaN/Inf weight 无法进入合法 `VerifiedRawResponse`（B2A `response_content_sha256` 已拒）；实现者测试以构造后 frame 漂移覆盖该边界，消费侧表现为 `G1_MEMBERSHIP_RESPONSE_INVALID`。

## 7. 下一步

等待**未参与本轮实现**的独立初验 Agent 出具  
[`M3_G1_P2_B3PIT成员状态独立初验报告.md`](M3_G1_P2_B3PIT成员状态独立初验报告.md)  
（须增加实现报告未使用的对抗性反例）。初验通过后由主 Agent 终验；在此之前不得更新路线图或宣称 P2/G1/Gate 通过。
