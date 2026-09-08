# M3 G1 BENCH-B1B-R4：快照前置短路与 Manifest 版本混合外部返工交付报告

| 项 | 内容 |
|---|---|
| 角色 | 外部返工实现 Agent（全新会话，未参与 R3 实现/初验） |
| 模型 | `cursor-grok-4.5-high` |
| 权威任务 | `M3_G1_BENCH-B1B-R4_快照前置短路与Manifest版本混合返工任务单.md` |
| 缺口来源 | B1B 外部独立初验 FAIL 报告 §4.1 / §4.2 |
| 白名单 | 仅 R4 §4 五个文件 |
| 状态 | **R4 返工与定向证据已落地；不得宣布 B1B/G1 Gate** |

---

## 1. 缺口修复映射

### 1.1 缺口一：非法期望 snapshot 被前置错误短路

| 项 | 内容 |
|---|---|
| 现象 | 非法 `expected_benchmark_source_snapshot_id` 与 empty bars / missing source / `H00300.CSI` / Schema 失败组合时，无任何 `BENCHMARK_SNAPSHOT_*` |
| 根因 | 期望格式校验嵌在 `benchmark == 510300.SH and selected_bench is not None` 分支 |
| 修复 | 入口无条件校验期望格式；非法只记一次 `BENCHMARK_SNAPSHOT_INVALID`。实际唯一性/格式与合法 mismatch 仍仅在可消费 `selected_bench` 路径检查；不重复期望非法错误，不从非法 bars 提取 identity |
| 证据 | `test_b1b_r4_illegal_expected_not_short_circuited`（参数化组合）；`test_b1b_r4_legal_expected_precondition_no_fabricated_snapshot`；`test_b1b_r4_illegal_expected_single_fail_closed_on_valid_path` |

### 1.2 缺口二：v1/v2 manifest 接受错误 mapper version

| 项 | 内容 |
|---|---|
| 现象 | `m3-g1-manifest-v2` + `m3-g1-tushare-mapper-v1` 可解析为 `G1ManifestV2` |
| 根因 | common validator 仅要求 `mapper_version` 非空字符串；v1/v2 均未锁定精确字面量 |
| 修复 | 在 `m3_release.py` 定义 `_MANIFEST_MAPPER_VERSION_V1/V2`；`G1ManifestV1`/`G1ManifestV2.__post_init__` 精确锁定对应 mapper；互换、未知、空值、非字符串 fail closed。未放宽 `G1BuildSpec` mapper-v2 合同；publish 仍只生成 v2 |
| 证据 | `test_b1b_r4_manifest_mapper_version_exact_lock` |

---

## 2. 改动文件（严格白名单）

- `src/quant/research/m3/readiness.py`
- `src/quant/data/m3_release.py`
- `tests/unit/test_m3_readiness.py`
- `tests/unit/test_m3_g1_release.py`
- 本报告

未联网、未调真实 API、未写正式数据、未 publish；保持 LF，未整文件重排。

---

## 3. 验证命令与真实结果

解释器：`D:\Miniforge3\python.exe`（Windows 反馈环；**非** WSL Gate）

### 3.1 新增轻量定向

```text
pytest tests/unit/test_m3_readiness.py -k "b1b_r4 or b1b_r3" -q
→ 29 passed, 42 deselected in 3.99s

pytest tests/unit/test_m3_g1_release.py -k "b1b_manifest or b1b_r4" -q
→ 2 passed, 29 deselected in 2.31s
```

### 3.2 readiness 全文件

```text
pytest tests/unit/test_m3_readiness.py -q
→ 71 passed in 7.11s
```

### 3.3 Ruff / mypy / diff check

```text
ruff check readiness.py m3_release.py test_m3_readiness.py test_m3_g1_release.py
→ All checks passed!

mypy src/quant/research/m3/readiness.py src/quant/data/m3_release.py
→ Success: no issues found in 2 source files

wsl git diff --check -- <白名单四代码文件>
→ DIFF_CHECK_EXIT=0
```

### 3.4 明确未跑

- candidate / release 重 fixture（含分钟级 identity shuffle 等）
- workflow HISTORY 长测
- WSL Miniforge `base` 全量 Gate
- 真实联网 / 正式数据 / publish

---

## 4. 主 Agent / 独立复验待办

1. 必须由**未参与本 R4 实现**的全新 `cursor-grok-4.5-high` 会话写唯一 R4 复验报告，并增加至少一个组合短路或 mapper 版本类型反例。
2. R4 复验通过后，才重新进入 B1B 主验。
3. 真实 `S=637` / 生产 plan 3190、HISTORY 长测、WSL Gate 仍属主 Agent 待验，不在本轮范围。

---

## 5. 明确非结论

- **不宣布** B1B 关闭
- **不宣布** G1 Gate 通过
- 定向绿测 ≠ 平台终验；fixture 绿 ≠ 真实数据 Gate
