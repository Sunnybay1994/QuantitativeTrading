# M3 G1-P4A 候选与主审计独立初验报告

日期：2026-07-14  
角色：**外部独立初验 Agent**（未参与 G1-P4A 实现；只读验收）  
实际模型标识：`cursor-grok-4.5-high`  
任务书：[`M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md`](M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md) §4 / §8 / §9  
上游主验：[`M3_G1_P2_B3PIT成员状态主Agent最终验收报告.md`](M3_G1_P2_B3PIT成员状态主Agent最终验收报告.md)、
[`M3_G1_P3_B2C执行事实主Agent最终验收报告.md`](M3_G1_P3_B2C执行事实主Agent最终验收报告.md)  
实现交付：[`M3_G1_P4A候选与主审计交付报告.md`](M3_G1_P4A候选与主审计交付报告.md)  
位置约定（主 Agent 已解决）：`HistoryWindow` ∈ `quant.data.m3_backfill`；
`G1QualityIssue` ∈ `quant.data.m3_g1_candidate`

**结论：独立初验通过（进入主验的前置条件满足）。**

本报告**不宣称**主验通过，也**不宣称** P4A / B4 / G1 / 任一 Gate 通过。

---

## 1. 验收边界与方法

- 只读核对生产代码、Schema、配置与实现者测试；未修改上述任何文件。
- 唯一仓库写入：本独立初验报告。
- 对抗探针仅置于 WSL `/tmp/p4a_adv/`，验收结束后清理；未联网、未读 token、未访问 `_old/`。
- 全部 Python / pytest / Ruff / mypy 经 `wsl.exe` 在
  `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，使用
  `/home/mabw/miniforge3/bin/conda run -n base`；禁止 Windows Python/conda。
- 不得只复述交付报告或只看绿测：逐项映射 §4/§8/§9，并补实现者未使用的对抗变体。

---

## 2. 文件范围与位置核对（§4.1 / §4.10）

| 检查项 | 证据 | 结果 |
|---|---|---|
| 允许范围内新增/导出 | `m3_g1_candidate.py`、`AdjustmentFactorMatchSchema`、`data/__init__.py`、`domain/__init__.py`、`test_m3_g1_candidate.py`、交付报告 | 符合 |
| 未把 B4 塞进 `m3_backfill.py` | `HistoryWindow` 仍在 `m3_backfill`；P4A 逻辑在 `m3_g1_candidate` | 符合 |
| `G1QualityIssue` 模块位置 | `__module__ == quant.data.m3_g1_candidate`（对抗探针确认） | 符合主 Agent 约定 |
| 无 research / connector IO | `m3_g1_candidate.py` 无 `quant.research`、无 `open`/`socket`/`RawStore`/`urllib` 调用 | 符合 |
| 公开导出 | `quant.data` 导出 build/verify/audit/apply 与冻结类型；`G1_MEMBERSHIP_METHOD_VERSION` | 符合 |

---

## 3. §4 契约逐项映射

### 3.1 接口与稳定异常（§4.2）

| 契约 | 核对 | 结果 |
|---|---|---|
| 四稳定错误码 + `from None` | `M3G1CandidateError`；P2/P3 异常归一 `COMPONENT_INVALID` | 通过 |
| `str/repr/cause` 脱敏 | 实现者测 + 初验对抗四码全表面扫描 | 通过 |
| 公开签名 | `build/verify/audit/apply_adjustment_factors_strict` 与任务书一致 | 通过 |

### 3.2 request/response 闭包与组件重建（§4.3）

| 契约 | 核对 | 结果 |
|---|---|---|
| 仅接受 `G1BuildInputs`；不可注入 P2/P3 result | 字段集无 membership/CA result；多余 kwargs → `TypeError`（对抗） | 通过 |
| plan/response 精确多重集合 | 实现者少/多/重复；初验 cross-wire frame、duplicate | 通过 |
| 完整 `verify_observed_membership_result(batch/responses/...)` | `_build_candidate_body` L1178 调用完整 verifier | 通过 |
| P3 selection/reconciliation 从 verified raw 重算 | `select_g1_corporate_actions` + `reconcile_g1_corporate_actions`；传入 daily responses + suspensions | 通过 |
| `event_ids_json` 进入 candidate | reconciliation 含列；重建后 NO_EVENT 为 `[]`；篡改+同步 digest 被 audit/verify 拒绝（对抗） | 通过 |
| 因子精确连接 + lineage，无默认 1.0 | `apply_adjustment_factors_strict`；实现者缺/重/非正/lineage | 通过 |
| 14 表 digest + required-keys + primary identity | 字典序 `_TABLE_NAMES`；`clean_table_content_sha256` | 通过 |
| `verify_g1_candidate(inputs=...)` 全量重建比较 | 重建后比 key/digests/receipts/dates/全表 | 通过 |

### 3.3 global audit（§4.5）

| 契约 | 核对 | 结果 |
|---|---|---|
| 跨表问题全收集、不首错即停 | 对抗同时破坏 eligible/bar/calendar → ≥2 个不同码 | 通过 |
| 无 `CROSS_SOURCE_*` | issue 码集不含；构造 `CROSS_SOURCE_MISMATCH` 被拒绝 | 通过 |
| `passed` ⇔ issues 空；全 ERROR | `G1PrimaryAuditResult.__post_init__`；对抗确认 | 通过 |
| Schema/digest/identity/eligible/bar-suspension/factor/benchmark/price-limit/CA | 代码路径存在；实现者 + 对抗抽样覆盖 | 通过 |

### 3.4 dataclass exact type / finite / 排序 / 自证（§3 公共类型）

| 契约 | 对抗 | 结果 |
|---|---|---|
| `factor_ratio_rtol` exact float、finite、∈[0,0.01]；拒 bool/int/NaN/0.02 | 是 | 通过 |
| receipts 排序；audit issues 排序 | 是 | 通过 |
| `passed` exact bool（拒 `1`） | 是 | 通过 |
| P4A candidate receipts 仅 tushare | `G1Candidate` 拒绝非 tushare | 通过 |

---

## 4. 实现者自测 vs 初验对抗（§4.6 / §8）

实现者 `tests/unit/test_m3_g1_candidate.py`（16）已覆盖 §4.6 主路径。初验**未复用**其断言写法，另增 `/tmp` 对抗（11）：

| # | 对抗变体（实现者未用） | 结果 |
|---|---|---|
| 1 | wholesale：另一合法 candidate 整包替换；以及把对方 frames 嫁接到原 plan/receipts 并**resync digests** 后，对原 inputs 的 `verify` 仍拒绝 | PASS |
| 2 | 14 表**逐表** digest 漂移 + 三表 digest/primary/required-keys **组合**漂移 | PASS |
| 3 | receipt 逆序拒绝；跨 response frame 接线拒绝；duplicate multiset | PASS |
| 4 | P2/P3 result 不可注入（签名/字段/kwargs） | PASS |
| 5 | audit 多 issue 全收集且无 CROSS_SOURCE | PASS |
| 6 | dataclass exact type/finite/排序/自证（含 CROSS_SOURCE 码拒绝） | PASS |
| 7 | 零 IO/网络加强：`open` 数据路径 + `socket.connect/connect_ex` + `urlopen` + RawStore | PASS |
| 8 | 四错误码观察面脱敏 | PASS |
| 9 | `event_ids_json` 经重执行进入 candidate；篡改+同步 digest 仍被拒；原 inputs rebuild 恢复 `[]` | PASS |
| 10 | `HistoryWindow` / `G1QualityIssue` 模块位置 | PASS |
| 11 | baostock receipt 不能进入 P4A candidate | PASS |

---

## 5. §9 验证命令（本机复跑）

全部经 WSL Miniforge `base`：

| 命令 | 结果 |
|---|---|
| 定向 `pytest -q tests/unit/test_m3_g1_candidate.py` | **16 passed**（约 5.6 min） |
| 初验对抗 `/tmp/p4a_adv/test_p4a_adversarial.py` | **11 passed**（约 5.0 min） |
| 全量 `PYTHONPATH=src pytest -q` | **625 passed**（既有 Pandera/Polars deprecation warnings） |
| `ruff check src tests` | **All checks passed** |
| `mypy src` | **77 source files，0 issues** |

---

## 6. 已知非阻断观察（不阻止初验通过）

1. 实现者 `test_membership_count_calendar_unknown_and_benchmark` 中未知证券分支有裸 `except Exception: pass`，对抗覆盖偏软；生产 audit 仍会收 `UNKNOWN_INSTRUMENT`/`SCHEMA_INVALID`。属 §7 可记录项，非来源闭包缺口。
2. 夹具无真实分红事件，MATCHED 路径的 `event_ids_json` 依赖 P3 已主验契约 + P4A 重执行调用；初验以 NO_EVENT 列落地 + 篡改自证闭合覆盖来源边界。主验若需 MATCHED 隐藏反例，可另造含实施分红的输入。
3. 交付报告 §7 曾记录 SSOT 位置表述冲突；现行 §4.10 与源码已与主 Agent 约定一致，初验按现行约定验收。

---

## 7. 交付声明

- **独立初验：通过**（职责：外部独立初验 Agent；证据含契约映射 + 实现者未用对抗 + §9 复跑）。
- **不宣称**主 Agent 终验通过。
- **不宣称** P4A / B4 / G1 / 任一 Gate 通过。
- **不得**开始 P4B/P4C；下一步仅交主 Agent 终验。

临时探针目录 `/tmp/p4a_adv/` 已在出具本报告后清理。
