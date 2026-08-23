# M3 G1 BENCH-B1B-R4：快照前置短路与 Manifest 版本混合外部独立复验报告

| 项 | 内容 |
|---|---|
| 角色 | 外部独立复验 Agent（全新会话，未参与 R4 实现） |
| 模型 | `cursor-grok-4.5-high` |
| 权威任务 | `docs/framework/agent/M3_G1_BENCH-B1B-R4_快照前置短路与Manifest版本混合返工任务单.md` |
| 实现证据 | `docs/framework/agent/M3_G1_BENCH-B1B-R4_快照前置短路与Manifest版本混合外部返工交付报告.md` |
| 缺口来源 | `docs/framework/agent/M3_G1_BENCH-B1B_510300总回报映射与全链身份重基线外部独立初验报告.md` §4.1 / §4.2（FAIL） |
| 只读约束 | 生产代码与实现者测试严格只读；未联网、未调真实 API、未写正式数据、未 publish |
| 唯一写入 | 本报告 |
| 复验结论 | **PASS**（R4 两缺口均已闭合；定向证据充分） |
| Gate | **不得、亦不宣布** B1B 关闭或 G1 Gate 通过 |

---

## 1. 范围与证据基线

已完整阅读：`AGENTS.md`、`.ai/README.md`、`.ai/coding_rules.md`、R4 任务书、R4 外部返工交付报告、上一份 B1B 独立初验 FAIL 报告 §4.1/§4.2，以及白名单四代码文件当前工作区 diff。

本轮仅复验 R4 冻结的两个缺口与实现者声明的轻量验证面；**未**启动 candidate/release 重 fixture、workflow HISTORY 长测、WSL Miniforge `base` 全量 Gate。

解释器：`D:\Miniforge3\python.exe`（Windows 反馈环；**非** WSL Gate）。

---

## 2. 缺口一复验：非法期望 snapshot 不被前置错误短路

### 2.1 合同要点

- 期望 snapshot 格式校验必须在 `audit_m3_readiness` 入口无条件执行。
- 非法期望只产生一次由期望自身触发的 `BENCHMARK_SNAPSHOT_INVALID`；消息含「期望」、不含完整 identity。
- 实际唯一性/格式与合法 mismatch 仍只在可消费 `selected_bench` 路径检查；不得从非法 bars 提取 identity。
- 合法 expected 与前置错误组合不得凭空产生 snapshot mismatch。

### 2.2 代码核对（只读）

`src/quant/research/m3/readiness.py`：

- 入口：`expected_ok = _is_sha256_hex(...)`；非法立即追加一次 `BENCHMARK_SNAPSHOT_INVALID`（消息「期望 benchmark source_snapshot_id 非法」）。
- `_check_benchmark_snapshot_binding(..., expected_ok=...)` 仅在 `benchmark == 510300.SH and selected_bench is not None` 时调用；`expected_ok=False` 时不重复期望非法、不发 `MISMATCH`。

判定：与 R4 §2 边界一致。

### 2.3 实现者测试复跑

```text
pytest tests/unit/test_m3_readiness.py -k "b1b_r4 or b1b_r3" -q
→ 29 passed, 42 deselected

pytest tests/unit/test_m3_readiness.py -q
→ 71 passed
```

覆盖：非法 expected × {empty bars, missing source, H00300, schema_missing_close}；合法 expected 前置无虚构 snapshot；合法路径上非法 expected 仅一次。

### 2.4 实现者未使用的对抗反例（本会话新增）

实现者 R4 矩阵仅用 `drop("close")` 作为 Schema/列失败代表；**未**覆盖 `source_snapshot_id`/`open` 缺列、extra 列、以及缺列+extra 组合。

本会话只读探针（不改仓库）：

| 组合 | 期望 | 其他码 | 期望侧 SNAPSHOT_INVALID 次数 | 结果 |
|---|---|---|---|---|
| 非法 expected ∈ {`""`, `"AB"*32`, `True`, `None`, `123`} × drop `source_snapshot_id` | 无条件 INVALID | `BENCHMARK_MISSING_FIELDS` | 1（消息含「期望」） | PASS |
| 同上 × drop `open` | 同上 | `BENCHMARK_MISSING_FIELDS` | 1 | PASS |
| 同上 × `extra_flag` 列 | 同上 | `BENCHMARK_INVALID` | 1 | PASS |
| 同上 × drop `close` + `extra_flag` | 同上 | `BENCHMARK_MISSING_FIELDS` | 1 | PASS |
| 合法 `_HEX_SNAP` × 上述四类列异常 | 无 SNAPSHOT_* | 对应其他码 | 0（无虚构 mismatch） | PASS |
| 非法 `""` + 合法 selected_bench 路径 | 仅一次 INVALID | — | 1 | PASS |

对抗小计：缺口一相关 **25/25 PASS**。

**缺口一结论：PASS。**

---

## 3. 缺口二复验：v1/v2 manifest mapper version 精确锁定

### 3.1 合同要点

- v1 精确接受 `m3-g1-tushare-mapper-v1`；v2 精确接受 `m3-g1-tushare-mapper-v2`。
- 互换、未知、空值、非字符串 fail closed；正确 v1/v2 仍可读。
- 不得放宽 `G1BuildSpec` mapper-v2 合同；不得把 v1 静默升级为 v2。

### 3.2 代码核对（只读）

`src/quant/data/m3_release.py`：

- `_MANIFEST_MAPPER_VERSION_V1/V2` 显式常量。
- `G1ManifestV1.__post_init__` / `G1ManifestV2.__post_init__` 分别 `!=` 精确字面量则 `ValueError("manifest mapper_version 非法")`。
- common validator 仍要求非空 `str`，但不替代精确锁定。

### 3.3 实现者测试复跑

```text
pytest tests/unit/test_m3_g1_release.py -k "b1b_manifest or b1b_r4" -q
→ 2 passed, 29 deselected
```

覆盖：正确 v1/v2 可读；v1↔v2 互换拒绝；未知/`""`；`True`/`123` 非字符串。

### 3.4 实现者未使用的对抗反例（本会话新增）

实现者未覆盖大小写变体、前后空白、空白串、`False`/`0`/`None`/list 等。

| 探针 | 结果 |
|---|---|
| 正确 v1 / v2 仍解析为 `G1ManifestV1` / `G1ManifestV2` | PASS |
| v2+v1 / v1+v2 互换 | fail closed（`ValueError`） |
| 全大写 / 混合大小写字面量 | fail closed |
| 前导/尾随空格、双侧空格 | fail closed |
| 纯空白 `"   "` / `"\t"` | fail closed |
| 未知 mapper / 空串 | fail closed |
| `True` / `False` / `0` / `None` / `["m3-g1-tushare-mapper-v2"]` | fail closed |

对抗小计：缺口二相关 **21/21 PASS**。

**缺口二结论：PASS。**

---

## 4. 静态检查与 diff check

```text
ruff check readiness.py m3_release.py test_m3_readiness.py test_m3_g1_release.py
→ All checks passed!

mypy src/quant/research/m3/readiness.py src/quant/data/m3_release.py
→ Success: no issues found in 2 source files

wsl git diff --check -- <白名单四代码文件>
→ DIFF_CHECK_EXIT=0
```

---

## 5. 对抗探针总览

| 分类 | 通过 | 失败 |
|---|---|---|
| 缺口一（缺列/extra/合法对照/单次） | 25 | 0 |
| 缺口二（bool/大小写/空白/互换/未知/正确读） | 21 | 0 |
| **合计** | **46** | **0** |

本会话对抗探针均在临时脚本中执行，**未**写入生产代码或实现者测试文件。

---

## 6. 明确未验范围

- candidate / release 重 fixture（含分钟级 identity shuffle 等）
- workflow HISTORY 长测
- 真实 `S=637` / 生产 plan 3190
- WSL Miniforge `base` 全量 Gate / 平台特有终验
- 真实联网、正式数据、publish 路径端到端
- B1B 其余非 R4 合同面的主验闭合

---

## 7. 结论与后续

| 项 | 判定 |
|---|---|
| R4 缺口一（期望 snapshot 前置短路） | **PASS** |
| R4 缺口二（manifest mapper 版本混合） | **PASS** |
| R4 外部独立复验总评 | **PASS** |
| B1B 关闭 / G1 Gate | **不宣布** |

R4 两缺口已具备进入主 Agent 下一阶段（重新进入 B1B 主验）的**前置复验通过**证据；定向绿测 ≠ Gate。主验仍须自行核对跨模块不变量、未公开反例与平台终验范围。
