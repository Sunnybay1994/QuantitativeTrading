# M3 G1-P4A 主验一次返工交付报告

日期：2026-07-14  
角色：外部实现 Agent（原 P4A 实现会话返工；非独立复验）  
实际模型标识：`cursor-grok-4.5-high`  
返工任务单：[`M3_G1_P4A主验一次返工任务单.md`](M3_G1_P4A主验一次返工任务单.md)  
合同补充：[`M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md`](M3_G1_P4_B4候选审计跨源发布设计与任务拆分.md) §3  
原交付：[`M3_G1_P4A候选与主审计交付报告.md`](M3_G1_P4A候选与主审计交付报告.md)  
状态：**返工已交，待独立复验**（不得视为 P4A / B4 / G1 / Gate 通过）

## 1. 范围与边界

只修主验 P1-1：`G1Candidate` 构造器身份闭包。未开始 P4B/P4C；未改 P2/P3、connector、
RawStore、配置、Schema 导出或路线图；未联网、未读 token、未访问 `_old/`；未写数据/release。

允许且实际修改：

| 文件 | 变更 |
|---|---|
| `src/quant/data/m3_g1_candidate.py` | constructor identity closure |
| `tests/unit/test_m3_g1_candidate.py` | 直接构造 / `replace` 攻击测试 |
| `docs/M3_G1_P4A主验一次返工交付报告.md` | 本报告 |

## 2. 现象—根因—修复映射

| 任务单项 | 处理 |
|---|---|
| 现象：`replace` 伪造 primary key / 改 frame 留旧 digest / 伪造 required(+key) 可构造 | 构造即失败，`G1_CANDIDATE_IDENTITY_MISMATCH` |
| 根因：constructor / audit / verify 职责混淆 | 抽取 `_verify_candidate_identity_closure`；audit/verify 语义保留 |
| §3：hex 检查不构成自证 | 对象内重算 14 digest、required digest、primary key 并精确相等 |

## 3. 冻结最小实现对照（任务单 §3）

1. `_verify_candidate_identity_closure`：无 IO、无网络；不调用 `audit_g1_candidate`；不要求 `G1BuildInputs`；由 `G1Candidate.__post_init__` 调用。
2. `_TABLE_ATTRS` / `_TABLE_SCHEMAS` 与 `_TABLE_NAMES` 唯一映射；逐表 Schema 验证；`eligible_keys` 走 `_canonical_eligible_keys`；规范化 frame `object.__setattr__` 写回。
3. 用现行 `clean_table_content_sha256` 按表名字典序重算 14 digest，与字段精确相等。
4. `_recompute_required_keys_digest` 从对象内 calendars/instruments/eligible_keys/suspensions + 四日期/现行规则经 `require_g1_price_limit_coverage` 重建 required keys，再 hash；不从 price-limit 行倒推。
5. 用规范 build spec、`plan_sha256`、四日期、排序 receipts、重算 digests/required 调 `_primary_candidate_key`，与字段精确相等。
6. 任一漂移 → 稳定 `G1_CANDIDATE_IDENTITY_MISMATCH`；非法类型/Schema 走现行边界；`__cause__ is None`；四观察面脱敏。
7. `verify_g1_candidate(inputs=...)` 来源闭包与 `audit_g1_candidate` 多 issue 收集保留，未因 fail-fast 删除或弱化。

## 4. 新增/强化测试对照（任务单 §4）

| # | 要求 | 测试证据 |
|---|---|---|
| 1 | `replace(..., primary_candidate_key="f"*64)` 失败 | `test_constructor_rejects_primary_key_replace`（含直接构造） |
| 2 | 14 表逐表 frame 漂移、旧 digests/key | `test_constructor_rejects_per_table_frame_drift`（`replace` + `G1Candidate(**)`） |
| 3 | 只改 table digest 并同步 primary key | `test_constructor_rejects_digest_only_and_required_key_drift` |
| 4 | 只改 required；或 required+key 同步、domain 不变 | 同上 |
| 5 | 安全 coercion 写回规范 frame；有损拒绝 | `test_constructor_coercion_writeback_and_lossy_reject` |
| 6 | 攻击覆盖 constructor 与 `replace`；脱敏 | primary / per-table / digest+required 双路径；`_assert_identity_reject` |
| 7 | build→constructor→audit→verify 不回归；wholesale 仍由 verify 拒 | `test_happy_path_build_verify_audit`；`test_wholesale_candidate_replacement_fails_verify` |

业务审计用例在需合法变异对象处使用 `_rebind_identity`（先 Schema 规范化再重算 digest/key），避免与身份闭包冲突。

## 5. 验证结果（WSL Miniforge `base`）

全部经 `wsl.exe` → `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，解释器
`/home/mabw/miniforge3/bin/python`；禁止 Windows Python/conda。

| 命令 | 结果 |
|---|---|
| `PYTHONPATH=src python -m pytest -q tests/unit/test_m3_g1_candidate.py` | **33 passed**（约 5m44s） |
| 构造器攻击子集（primary / digest+required / coercion） | **3 passed**（约 40s；含 digest/required 直接构造补强） |
| `PYTHONPATH=src python -m pytest -q` | **642 passed**（约 6m43s；既有 Pandera/Polars deprecation warnings） |
| `python -m ruff check src/quant/data/m3_g1_candidate.py tests/unit/test_m3_g1_candidate.py` | All checks passed |
| `python -m mypy src/quant/data/m3_g1_candidate.py` | Success: no issues found |

## 6. 已知限制与交接

- 本报告只声明返工交付，不写独立复验报告，不勾选 Gate。
- 下一步：未参与本轮实现的全新 `cursor-grok-4.5-high` 会话只读生成
  `docs/M3_G1_P4A主验一次返工独立复验报告.md`；须直接攻击构造器并补实现者未用变体。
- 复验通过前不得开始 P4B/P4C，不得宣称 P4A/B4/G1/Gate 通过。
