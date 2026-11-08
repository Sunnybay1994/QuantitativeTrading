| 字段/组 | 数量 | 裁定 | consumer closure / 理由 |
|---|---:|---|---|
| `meta.purpose` | 1 | 拒绝 | 不被生产行为消费；以描述文字区分 hash 是无意义 identity，fold 已由 request 显式绑定 |
| `meta.enabled` | 1 | 拒绝 | acceptance upstream 明确要求 `True`，不能一 lane disabled |
| `g1_backfill.label_tail_sessions` | 1 | 拒绝 | 进入 g1+snapshot，改变采集尾部和 derived identities，不是纯执行 lane 参数 |
| `g1_backfill.request_rate_per_minute` | 1 | 候选 C1 | 实际 G1 rate limiter；无 config derived selector，但进入 static-plan SHA；须与 release lane 的真实 quota 证据一致 |
| `g1_backfill.max_attempts` | 1 | 候选 C2 | 实际 retry budget；无 config derived selector，但进入 static-plan SHA；须与 release lane 策略一致 |
| `g1_backfill.retry_base_seconds` | 1 | 候选 C3 | 实际 backoff；无 config derived selector，但进入 static-plan SHA；须与 release lane 策略一致 |
| `g1_backfill.reconciliation.{price_atol,price_rtol,volume_rtol,max_mismatch_rate}` | 4 | 拒绝 | 直接改变 G1 cross-source quality Gate，并进入 g1 identity |
| `g1_backfill.corporate_action_reconciliation.factor_ratio_rtol` | 1 | 拒绝 | 直接改变 corporate-action quality Gate，并进入 g1 identity |
| `validation.labels.{qlib_expression_atol,benchmark_return_atol,label_return_atol}` | 3 | 拒绝 | 直接改变 label reconciliation pass/fail；且有内部 tolerance ordering |
| `tracking.{experiment_name,tracking_uri}` | 2 | 拒绝 | 改变 canonical tracking target；fold artifacts/summary/acceptance tracking 需闭合到一致 target 语义 |
| `tracking.artifact_root` | 1 | 拒绝 | bridge 逐 config 求 stage root，要求 set size=1 且 exact controlled root |
| `acceptance.reproducibility_{score,metric}_atol` | 2 | 拒绝 | 直接改变 reproducibility Gate；aggregate 不能采用 lane-specific 松紧 |
| `acceptance.minimum_{feature,prediction,label,evaluation}_coverage` | 4 | 拒绝 | 直接改变 coverage Gate |
| `acceptance.minimum_computable_ic_date_ratio` | 1 | 拒绝 | 直接改变 evaluation computability Gate |
| **合计** | **24** | **3 candidate / 21 rejected** | coverage complete |

候选排序：C1 `request_rate_per_minute`（最清晰的外部配额语义）→ C3 `retry_base_seconds`（限频退避）→
C2 `max_attempts`（可靠性/失败预算）。排序不是值选择，也不授权三项都不同；future owner 应优先选择恰好一个能由真实 lane
资源合同证明的字段，并明确两个精确值、owner、API quota/调度依据和两 lane 对应关系。若没有真实差异依据，则这三个候选
也必须全部拒绝，并进入 `NO_JUSTIFIED_DIFFERENCE / ARCHITECTURE_REVIEW_CANDIDATE`，不能为了满足 runtime 人造差异。

## 6. 强制反例复核

1. 只改 TOML 注释/空白：raw 可不同，normalized full 相同；runtime 因 full identity set size=1 拒绝。
2. 改日期/window/model 等任一 scientific 字段：raw/full 不同，但 scientific set size=2；runtime 拒绝。
3. 改 fixed literal 或加 unknown field：strict loader 在 runtime 前拒绝。
4. 改 reconciliation/label/acceptance tolerance 只为 hash：虽 non-scientific，但改变质量/准入 Gate，候选判据不通过。
5. 改 tracking experiment/URI：另算 tracking target key，且 downstream tracking/aggregate 闭包不再共享；不准入。
6. 改 artifact root：bridge 要求两个 `project_stage_root` 相同并等于 controlled root，直接拒绝。
7. example/fixture 展示两个不同 rate/retry 值：仍不是正式 SSOT；本轮未读取其具体值，也不构成 USER_CHOICE。

## 7. 边界、未决项与交付状态

本轮未运行 Python、pytest、Ruff、mypy 或 Qlib；未创建 config、request、root、evidence；未修改 runtime/schema/tests/
taskbook/review；未 stage/commit。唯一新增文件是本 delivery。

仍需 user/研究及运行资源 owner 决定：是否确有两个 G1 获取 lane 的不同配额/重试合同；若有，选择 C1/C2/C3 中的
具体字段、两个精确值及 lane 映射，并证明不借此弱化 fail-closed 行为。该决定之前不得创建 formal config。

交付上限：

`NONSCIENTIFIC_DIFFERENCE_INVENTORY_FROZEN / CONTRACT_STOP / USER_CHOICE_REQUIRED`

本包不关闭 A13/A14/A16/A19，不推进 actual successor、Qlib 或 M3 Gate；下一步仅允许不同独立 reviewer 静态复核
148/148 coverage、候选的 consumer 闭包和“无真实业务依据则架构重审”的 fail-closed 分支。
