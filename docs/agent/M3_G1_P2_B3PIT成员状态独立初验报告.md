# M3 G1-P2 B3：PIT 成员状态独立初验报告

日期：2026-07-14  
角色：**外部独立初验 Agent**（从未参与 G1-P2 B3 实现）  
实际模型标识：`cursor-grok-4.5-high`  
权威任务书：[`M3_G1_P2_B3PIT成员状态外部闭环任务单.md`](M3_G1_P2_B3PIT成员状态外部闭环任务单.md)  
实现线索（不作唯一证明）：[`M3_G1_P2_B3PIT成员状态交付报告.md`](M3_G1_P2_B3PIT成员状态交付报告.md)  
主契约：[`M3实施与Agent交接.md`](../M3实施与Agent交接.md) §4.10  
上游已验收：[`M3_G1_B2A主Agent最终验收报告.md`](M3_G1_B2A主Agent最终验收报告.md)、[`M3_G1_P1主Agent最终验收报告.md`](M3_G1_P1主Agent最终验收报告.md)  
配置前置：[`M3_G1_P2_0主Agent最终验收报告.md`](M3_G1_P2_0主Agent最终验收报告.md)

## 结论

**外部独立初验不通过，退回实现 Agent 返工。**

本报告不宣称 B3 / P2 / G1 / Gate 完成。唯一仓库写入为本报告；未修改生产代码、配置、Schema、实现者测试或任务书；未联网、未读 token、未访问 `_old/`。临时对抗脚本仅位于 WSL `/tmp`，验收后已清理。

阻断项：**P1-1**（`ObservedMembershipResult` 构造边界未消费 Schema 返回 frame，digest 与暴露表 dtype 可脱钩）。身份闭包与 Schema-first 不得降为 P2。

---

## 1. 修改范围核对

| 文件 | 是否在任务书 §10 允许范围 | 独立核验 |
|---|---|---|
| `src/quant/data/index_membership.py` | 允许新增 | 存在；公开签名与任务书 §4 一致 |
| `src/quant/data/m3_identity.py` | 允许新增 | 存在；`m3-clean-table-content-v1` |
| `src/quant/domain/schemas.py` | 允许新增 Schema | `IndexConstituentObservationSchema` strict/coerce；唯一键正确 |
| `src/quant/data/__init__.py` | 仅追加导出 | 已导出五个 B3 符号 + identity 二者 |
| `src/quant/domain/__init__.py` | 仅追加导出 | 已导出 `IndexConstituentObservationSchema` |
| `tests/unit/test_index_membership.py` | 允许新增 | 17 个测试函数，覆盖 §11 矩阵主路径 |
| `tests/unit/test_m3_identity.py` | 允许新增 | 6 个测试函数 |
| `docs/M3_G1_P2_B3PIT成员状态交付报告.md` | 允许 | 已读；未宣称 Gate |

未见对 B2A/B2B 已验收生产代码、配置、路线图或 Gate 状态的越权修改（只读审查范围内）。

---

## 2. 冻结接口与不变量证据映射

| 冻结项 | 源码证据 | 结果 |
|---|---|---|
| 公开函数/类型签名 | `index_membership.py` / `m3_identity.py` 与任务书 §4 一致 | 通过 |
| universe / source / index / count 硬约束 | `_UNIVERSE`、`_SOURCE`、`_INDEX_CODE`、`_EXPECTED_COUNT=300`；`expected_constituent_count != 300` 拒绝 | 通过 |
| 请求闭包先于读值 | `_consume_batch` → `_validate_index_weight_batch` → `_consume_responses` → `_match_response_set` 后才 `iter_rows` | 通过 |
| 完整自然月、月份唯一连续 | `_validate_index_weight_batch` | 通过（对抗 C2b） |
| response request_id 多重集合 | `_match_response_set` + Counter | 通过 |
| 每 observation 恰 300 + `math.fsum` `[99,101]` | `_assert_observation_groups` | 通过 |
| PIT：下一 SH session 收盘后 `as_of` | `_next_session` 作 activation；Friday 无资格 | 通过（实现者 fixture + 对抗 C5） |
| warmup / `effective_to` 非 null / signal 裁剪 | `_clip_and_merge_intervals`、`_assert_membership_invariants` | 通过 |
| calendar_proof_end + SH/SZ 逐日一致 | `_prepare_calendar` | 通过（实现者测试 + 范围核对） |
| instrument 生命周期 session 映射 | `_first_session_on_or_after` / `_last_session_on_or_before` | 通过（对抗 C6） |
| `verify` 从 batch/responses 重跑 normalize+build | `verify_observed_membership_result` | 通过（对抗 C9；亦能抓住 P1-1 伪造） |
| 稳定错误码集合 | `_ERROR_CODES` 与任务书 §9 一致；未知 code 拒绝 | 通过 |
| clean digest v1 | `m3_identity.py`：`-0.0→0.0`、行序稳定、datetime 拒绝、重复保留 | 通过（对抗 C8） |
| 无网络/文件写/research 反向 import | 生产源码静态扫描无 `socket`/`urllib`/`write_parquet`/`qlib`/`quant.research` | 通过 |
| **Result 构造消费 Schema 返回 frame** | `__post_init__` 验 Schema 算 digest，但**未** `object.__setattr__` 写回 validated frame | **失败 → P1-1** |

---

## 3. 实现者未使用的对抗性反例（任务书 §12）

临时脚本 `/tmp/b3_adv_verify.py`（已清理）。覆盖 §12 所列类别中 **10/10**（超过最低 6 类），数据与组合未复用实现者精确用例。

| ID | 类别 | 对抗要点（相对实现者差异） | 结果 |
|---|---|---|---|
| C1 | 多层漂移 + 自洽伪造 | batch hash 漂移；frame+receipt_sha 同时漂移；自洽重算 content/stable 后权重越界 | **PASS**（`BATCH_INVALID` / `RESPONSE_INVALID` / `WEIGHT_SUM_INVALID`） |
| C2 | 跳月 / scope 错配 | 正确 hash 的 Jan+Mar 不连续 batch；ID 集 Jan+Mar vs batch Jan+Feb；同 ID 毒化 frame | **PASS**（`REQUEST_SCOPE_INVALID` / `RESPONSE_SET_MISMATCH` / `RESPONSE_INVALID`） |
| C3 | 跨 response 重复观察键 | Feb spec + Jan 日期自洽 receipt；两份各自唯一 frame concat | **PASS**（`REQUEST_SCOPE_INVALID` / `DUPLICATE_KEY`） |
| C4 | Schema coercion vs List | Utf8 weight 可 coercion；List[Float64] 不可 coercion；确认 validate 返回 Float64 | **PASS**（build 路径消费 coerced；List → `OBSERVATION_SCHEMA_INVALID`） |
| C5 | Friday 调入/调出 | 2016-01-29 观察含成员更替；Friday 无 `as_of`；Mon 旧集 / Mar 新集 | **PASS** |
| C6 | 周末 delist + 重入 + 合并 | `delist_date=2016-04-02` 周六；调出再入两段；持续成员一段 | **PASS** |
| C7 | warmup：obs 在 start 前但 activation 晚于 start | `signal_start=2016-01-28`（开市）且首 activation=`2016-02-01` | **PASS**（`WARMUP_MISSING`） |
| C8 | clean digest | `-0.0/0.0`、Unicode、datetime 拒绝、重复行 | **PASS** |
| C9 | Result 局部/整体合法表替换 | 只换一 frame、只换一 hash、membership/eligible 整套换成另一合法窗口并同步 digest | **PASS**（`RESULT_INVALID`） |
| C10 | 恶意路径/token | `batch`/`table_name` 含 `/home/.../token=leak` 与 `G:\...`；扫描 cause/traceback | **PASS**（无泄露，`__cause__ is None`） |

**额外隐藏探针（构造 Schema-first，导致判定不通过）：**

将合法 `observations` 的 `observation_date` 转为 Utf8，用 Schema 强制转换后的 Date frame 计算 `observations_sha256`，再把**未转换**的 Utf8 frame 与该 digest 一并传入 `ObservedMembershipResult`：

- 构造 **成功**；
- 暴露 frame dtype 仍为 `String`，而 digest 来自 `Date`；
- `clean_table_content_sha256(exposed) != result.observations_sha256`；
- `verify_observed_membership_result` 正确拒绝为 `G1_MEMBERSHIP_RESULT_INVALID`。

→ 见 **P1-1**。实现者测试未覆盖“可 coercion dtype + 用 coerced digest 包装未消费 frame”的构造反例。

---

## 4. WSL 验证命令（Miniforge `base`，工作目录 `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`）

| 命令 | 结果 |
|---|---|
| `pytest -q tests/unit/test_index_membership.py tests/unit/test_m3_identity.py tests/unit/test_m3_backfill_requests.py tests/unit/test_m3_g1_mappers.py` | **166 passed** |
| `pytest -q`（全量） | **560 passed**（既有 Pandera/Polars deprecation warnings） |
| `ruff check src tests` | All checks passed |
| `mypy src` | Success: no issues found in 75 source files |
| 对抗脚本 | **25 PASS / 0 FAIL**（不含随后发现的 P1-1 探针） |
| P1-1 Schema-first 探针 | **复现成功**（构造接受 + digest≠exposed；verify 拒绝） |

未联网；未使用 Windows Python/conda 跑项目测试。

---

## 5. 返工项（现象—根因—应遵循规则—最小复现—新增测试—通过条件）

### P1-1：`ObservedMembershipResult` 未消费 Schema 返回 frame，digest 与暴露表可脱钩

| 字段 | 内容 |
|---|---|
| **现象** | 对合法 observations 将 `observation_date` cast 为 Utf8；用 `IndexConstituentObservationSchema.validate` 得到 Date frame 并据此计算 `observations_sha256`；把**未 coerce 的 Utf8 frame**与该 digest 传入 `ObservedMembershipResult`。构造成功，且 `result.observations["observation_date"].dtype == String`，同时 `clean_table_content_sha256(result.observations) != result.observations_sha256`。`verify_observed_membership_result` 能拒绝该对象，但公开 Result 已处于“digest 不描述暴露表”的状态。 |
| **根因** | `ObservedMembershipResult.__post_init__` 调用 Schema/`clean_table_content_sha256` 时使用的是 validator **返回**的 coerced frame，却未通过 `object.__setattr__` 把三张 validated frame 写回实例；frozen dataclass 继续暴露调用方传入的预验证对象。 |
| **应遵循规则** | 任务书 §5：「调用 Schema 后必须消费 validator 返回的 frame，不得继续使用验证前对象。」§8：构造时重验三表与三 digest，且 digest 必须绑定实际持有的 clean 表内容；身份闭包与 Schema-first 不得降为 P2。主契约 §4.10 同义：公开 verifier/构造闭包不能只检查 hex 而留下与 digest 不一致的 frame。 |
| **最小复现** | 1）`build_observed_membership` 得到合法 `result`；2）`str_obs = result.observations.with_columns(pl.col("observation_date").cast(pl.Utf8))`；3）`coerced = IndexConstituentObservationSchema.validate(str_obs)`；4）`d = clean_table_content_sha256(table_name="index_constituent_observation", frame=coerced)`；5）`ObservedMembershipResult(str_obs, result.membership, result.eligible_keys, d, result.membership_sha256, result.eligible_keys_sha256)` 不应构造成功；或构造成功时暴露 frame 必须为 Date 且 `clean_table_content_sha256(exposed)==d`。 |
| **新增测试** | 在 `tests/unit/test_index_membership.py` 增加：① 可 coercion 的 `observation_date` Utf8（或同类）+ coerced digest 包装未消费 frame → 构造失败 **或** 自动替换为 validated frame 且 digest 自洽；② 构造成功路径上 `clean_table_content_sha256(result.observations) == result.observations_sha256`（membership/eligible 同理）；③ 不可 coercion 的 List/Struct 列仍稳定 `G1_MEMBERSHIP_*_INVALID`。 |
| **通过条件** | 上述最小复现与新增测试稳定通过；`__post_init__` 对三张表均消费 Schema（及 eligible 校验）返回对象并写回；再对写回后的 frame 计算 digest 与 reported 比较；全量 pytest / ruff / mypy 仍绿；独立初验复跑 P1-1 探针与 §12 对抗通过。 |

---

## 6. 非阻断观察（不作为本轮通过条件）

- 正常 `build_observed_membership` / `normalize_index_weight_observations` 路径已消费 Schema 返回 frame（对抗 C4a 证实），PIT/300/calendar/lifecycle 主路径行为与任务书一致。
- `verify_observed_membership_result` 对 P1-1 伪造仍 fail-closed，说明消费侧 verifier 有效；缺口在 **Result 构造信任边界自身**。
- 交付报告中 NaN/Inf weight 依赖 B2A 拒收、以 frame 漂移覆盖的说明与实现一致，非矛盾。

---

## 7. 裁决与下一步

**外部独立初验不通过。**

请实现 Agent 仅针对 **P1-1** 做最小返工（优先在 `__post_init__` 写回 validated frames，并补回归测试），更新交付/返工报告后，由**未参与该轮实现**的另一外部初验 Agent 复验。复验通过前不得交主 Agent 终验，不得更新路线图或宣称 P2/G1/Gate 通过。
