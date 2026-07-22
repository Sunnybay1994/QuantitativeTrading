# M3 G1-P4A 主验一次返工独立复验报告

日期：2026-07-14  
角色：**外部独立复验 Agent**（未参与原 P4A 实现，亦未参与本轮返工；只读验收）  
实际模型标识：`cursor-grok-4.5-high`  
返工任务单：[`M3_G1_P4A主验一次返工任务单.md`](M3_G1_P4A主验一次返工任务单.md)  
合同补充：[`M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md`](M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md) §3  
返工交付：[`M3_G1_P4A主验一次返工交付报告.md`](M3_G1_P4A主验一次返工交付报告.md)  
原初验：[`M3_G1_P4A候选与主审计独立初验报告.md`](M3_G1_P4A候选与主审计独立初验报告.md)

**结论：独立复验通过（可交回主 Agent 终验）。**

本报告**不宣称**主验通过，也**不宣称** P4A / B4 / G1 / 任一 Gate 通过。

---

## 1. 验收边界与方法

- 只读核对生产代码、Schema、实现者测试与返工交付；未修改上述任何文件。
- 唯一仓库写入：本独立复验报告。
- 临时对抗探针仅置于 WSL `/tmp/p4a_reverify_probe.py`，验收结束后已清理；未联网、未读 token、未访问 `_old/`。
- 全部 Python / pytest / Ruff / mypy 经 `wsl.exe` 进入
  `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，解释器
  `/home/mabw/miniforge3/bin/python`（WSL Miniforge `base`）；禁止 Windows Python/conda。
- 重点直接攻击 `G1Candidate` 构造器与 `dataclasses.replace`，不得只调用 `audit`/`verify`；
  并补实现者未使用的对抗变体。

---

## 2. 源码结构核对（任务单 §3）

| # | 冻结要求 | 证据 | 结果 |
|---|---|---|---|
| 1 | 内部 identity verifier，无 IO/网络，不调用 audit，不要求 `G1BuildInputs` | `_verify_candidate_identity_closure`；源码无 `audit_g1_candidate`/`G1BuildInputs`；由 `G1Candidate.__post_init__` 调用 | 通过 |
| 2 | 14 表唯一映射；Schema/`eligible_keys` 规范；coercion 写回 | `_TABLE_ATTRS`/`_TABLE_SCHEMAS` 与 `_TABLE_NAMES` 双射；`object.__setattr__` 写回规范 frame | 通过 |
| 3 | `clean_table_content_sha256` 重算 14 digest 精确相等 | 写回后按 `_TABLE_NAMES` 重算并与字段比较 | 通过 |
| 4 | 从 calendar/instrument/eligible/suspension + 四日期重建 required domain | `_recompute_required_keys_digest` → `require_g1_price_limit_coverage`；不从 price-limit 行倒推 | 通过 |
| 5 | 独立重算 `primary_candidate_key` 精确相等 | 调 `_primary_candidate_key(recomputed digests, required, …)` | 通过 |
| 6 | 漂移 → `G1_CANDIDATE_IDENTITY_MISMATCH`；`__cause__ is None`；脱敏 | 对抗探针 + 实现者 `_assert_identity_reject` | 通过 |
| 7 | 不削弱 verify 来源闭包与 audit 多 issue | A5–A12 对抗 + 源码 `audit_g1_candidate` 持续收集 | 通过 |

---

## 3. 实现者测试覆盖 vs 复验新增攻击

实现者已有：`replace`/`G1Candidate(**)` 伪造 primary；14 表 frame 业务值漂移；digest/required 与**假** hex primary 同步；eligible Utf8 coercion；wholesale verify。

复验**额外**直接攻击（实现者未用变体）：

| ID | 攻击 | 期望 | 结果 |
|---|---|---|---|
| A1 | 伪造单表 digest，并用 `_primary_candidate_key` 算出**真实匹配** primary（非假 hex） | 构造/`replace` → `IDENTITY_MISMATCH` | PASS |
| A2 | 伪造 required digest + 真实匹配 primary；对象内 required domain 不变 | 同上 | PASS |
| A3 | bars **重复行**（非改值/截断） | Schema/`IDENTITY` 拒绝；`cause is None` | PASS（`INPUT_INVALID`） |
| A4 | `bar_1d.volume` Int64→Schema 写回 Float64；独立重算 14 digest 一致；lossy Utf8 close 拒绝 | 写回 + digest 自洽；lossy `INPUT_INVALID` | PASS |
| A5 | receipt `stable_response_sha256` 漂移：自洽 primary 可构造；`verify(inputs=原)` 拒；旧 primary 拒 | 构造身份 ≠ 来源闭包 | PASS |
| A6 | `build_spec.g1_config_sha256` 同上 | 同上 | PASS |
| A7 | `signal_end` 日期漂移同上 | 同上 | PASS |
| A8 | `plan_sha256`：plan 自证拒绝；`__new__` 绕过塞入 candidate 仍 `INPUT_INVALID` | plan 层先挡 | PASS |
| A9 | receipt + date **组合**自洽伪造；verify 拒 | 组合漂移仍由 verify 抓 | PASS |
| A10 | 同时缺 bar + FULL_DAY 冲突；audit 收集 ≥2 issue | 多 issue 未 fail-fast | PASS（2 codes） |
| A11–A14 | happy verify/audit；wholesale；verifier 结构；eligible coercion digest | 回归与写回 | PASS |

共 **26/26** 对抗项通过。

---

## 4. 任务单 §4 通过条件映射

| # | 要求 | 复验证据 | 结果 |
|---|---|---|---|
| 1 | `replace(..., primary="f"*64)` 失败 | 实现者测 + 源码 `__post_init__` | 通过 |
| 2 | 14 表 frame 漂移 | 实现者参数化测 | 通过 |
| 3 | 同步 table digest+primary | **A1**（真实 primary，强于假 hex） | 通过 |
| 4 | 同步 required+primary、domain 不变 | **A2** | 通过 |
| 5 | Schema coercion 写回后 digest | **A4** bars volume；**A14** eligible | 通过 |
| 6 | constructor 与 `replace`；脱敏 | A1–A7 双路径；`str/repr/cause` 无 `/home/`/`token` | 通过 |
| 7 | build→audit→verify 不回归；wholesale 仍由 verify 拒 | A11/A12；实现者 happy/wholesale | 通过 |

---

## 5. 验证命令（WSL Miniforge `base`）

| 命令 | 结果 |
|---|---|
| `/tmp` 对抗探针（constructor/`replace` 直接攻击） | **26 passed** |
| `PYTHONPATH=src python -m pytest -q tests/unit/test_m3_g1_candidate.py` | **33 passed**（约 5m46s；既有 Pandera/Polars deprecation warnings） |
| `PYTHONPATH=src python -m pytest -q` | **642 passed**（约 6m48s；同上类 warnings） |
| `python -m ruff check src/quant/data/m3_g1_candidate.py tests/unit/test_m3_g1_candidate.py` | All checks passed |
| `python -m mypy src/quant/data/m3_g1_candidate.py` | Success: no issues found |

---

## 6. 交接

- 本报告只声明：**主验一次返工的独立复验通过**，可将 P1-1 交回主 Agent 终验。
- **不宣称**主验 / P4A / B4 / G1 / Gate 通过；复验通过前本 Agent 未开始 P4B/P4C。
- 临时探针与中间日志已从 WSL `/tmp` 清理；仓库无探针残留。
